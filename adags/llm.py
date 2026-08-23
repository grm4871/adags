"""OpenAI-compatible LLM backends. Default is OpenRouter free (no token bill)."""

from __future__ import annotations

import json
import os
import re
import signal
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from adags.gov import as_impeach, as_member_id
from adags.hermes_backend import endpoint

# $/1M tokens. :free and openrouter/free are metered at 0.
RATES: dict[str, tuple[float, float]] = {
    "openrouter/free": (0.0, 0.0),
    "grok-4.3": (1.25, 2.50),
    "grok-4.6": (2.00, 6.00),
    "gpt-5.6-luna": (0.20, 1.20),
}

PROVIDERS: dict[str, dict[str, str]] = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "default_model": "nvidia/nemotron-3-super-120b-a12b:free",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "default_model": "gpt-5.6-luna",
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "key_env": "XAI_API_KEY",
        "default_model": "grok-4.3",
    },
}


def _rates_for(model: str) -> tuple[float, float]:
    if model.endswith(":free") or model == "openrouter/free":
        return (0.0, 0.0)
    if model in RATES:
        return RATES[model]
    return RATES.get("grok-4.3", (1.25, 2.50))


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    input_rate: float = 1.25
    output_rate: float = 2.50
    error: str | None = None
    cut: str | None = None

    @property
    def usd(self) -> float:
        return (
            self.input_tokens * self.input_rate / 1_000_000
            + self.output_tokens * self.output_rate / 1_000_000
        )


def _timeout_like(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return isinstance(exc, TimeoutError) or "timeout" in name or "timed out" in text


def _http_timeout(total: float, *, read: float):
    """Idle-read bound so a silent proxy cannot sit out the whole call timeout."""
    total = max(0.05, float(total))
    read = max(0.05, min(float(read), total))
    try:
        import httpx

        return httpx.Timeout(
            total, connect=min(5.0, total), read=read, write=min(5.0, total), pool=min(5.0, total)
        )
    except Exception:
        return read


class LLM:
    deadline: float | None = None
    remaining_usd: float | None = None

    def complete(
        self,
        *,
        system: str,
        user: str,
        on_token=None,
        on_think=None,
        prefix: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        raise NotImplementedError


class ChatLLM(LLM):
    """Any OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        json_mode: bool = True,
        extra_headers: dict[str, str] | None = None,
        rates: tuple[float, float] | None = None,
    ) -> None:
        from openai import OpenAI

        self.model = model
        self.json_mode = json_mode
        self._in_rate, self._out_rate = rates if rates is not None else _rates_for(model)
        self.timeout = float(os.environ.get("ADAGS_CALL_TIMEOUT", "60"))
        self.think_timeout = float(os.environ.get("ADAGS_THINK_TIMEOUT", "25"))
        # Hermes + a 120B model often sit silent longer than 8s before the
        # first byte. That was cutting live turns, not runaway plans.
        self.first_token_timeout = float(os.environ.get("ADAGS_FIRST_TOKEN_TIMEOUT", "20"))
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=extra_headers or None,
            timeout=_http_timeout(self.timeout, read=self.first_token_timeout),
            max_retries=0,
        )

    def complete(
        self,
        *,
        system: str,
        user: str,
        on_token=None,
        on_think=None,
        prefix: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        attempts: list[tuple[list[dict[str, str]], str | None]] = []
        if prefix:
            attempts.append(
                (messages + [{"role": "assistant", "content": prefix}], prefix)
            )
        attempts.append((messages, None))
        budgeted = self.remaining_usd is not None and bool(self._in_rate or self._out_rate)
        if budgeted:
            # A paid retry is another independently billable call. One bounded
            # attempt is the only way to keep the local cap meaningful.
            attempts = attempts[:1]
        last_exc: Exception | None = None
        completion_deadline = min(
            time.monotonic() + self.timeout,
            self.deadline if self.deadline is not None else float("inf"),
        )
        for msgs, pre in attempts:
            timeout = completion_deadline - time.monotonic()
            if timeout <= 0:
                return LLMResult(text="", error="wall-clock deadline reached")
            max_tokens = int(
                max_tokens
                if max_tokens is not None
                else os.environ.get("ADAGS_MAX_TOKENS", "1800")
            )
            if self.remaining_usd is not None and (self._in_rate or self._out_rate):
                # UTF-8 bytes are a conservative upper bound on prompt tokens.
                prompt_tokens = sum(
                    len(str(m.get("content") or "").encode("utf-8")) + 16
                    for m in msgs
                )
                input_cost = prompt_tokens * self._in_rate / 1_000_000
                output_room = self.remaining_usd - input_cost
                if output_room <= 0 or self._out_rate <= 0:
                    return LLMResult(text="", error="spend cap has insufficient room for another call")
                max_tokens = min(
                    max_tokens,
                    int(output_room * 1_000_000 / self._out_rate),
                )
                if max_tokens < 1:
                    return LLMResult(text="", error="spend cap has insufficient room for output")
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": msgs,
                "max_tokens": max_tokens,
                "temperature": 0.3,
                "timeout": _http_timeout(
                    timeout, read=float(getattr(self, "think_timeout", 12) or 12)
                ),
            }
            if self.json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            hook = _seeded_on_token(on_token, pre)
            try:
                result = self._complete_stream(
                    kwargs, hook, on_think, deadline=completion_deadline
                )
                result.text = apply_prefix(pre, result.text)
                return result
            except Exception as exc:
                last_exc = exc
                if _timeout_like(exc) or time.monotonic() >= completion_deadline:
                    break
                if self.json_mode and not budgeted:
                    kwargs.pop("response_format", None)
                    try:
                        result = self._complete_stream(
                            kwargs, hook, on_think, deadline=completion_deadline
                        )
                        result.text = apply_prefix(pre, result.text)
                        return result
                    except Exception as exc2:
                        last_exc = exc2
                continue
        return LLMResult(
            text="",
            input_tokens=0,
            output_tokens=0,
            input_rate=self._in_rate,
            output_rate=self._out_rate,
            error=f"{type(last_exc).__name__}: {last_exc}"[:200] if last_exc else "empty",
        )

    def _complete_stream(
        self, kwargs: dict[str, Any], on_token, on_think=None, *, deadline: float | None = None
    ) -> LLMResult:
        content_parts: list[str] = []
        think_parts: list[str] = []
        inn = out = 0
        started = time.monotonic()
        first_token_at: float | None = None
        speech_at: float | None = None
        think_limit = float(getattr(self, "think_timeout", 12) or 0)
        first_limit = float(getattr(self, "first_token_timeout", 8) or 0)
        deadline = deadline or min(
            time.monotonic() + self.timeout,
            self.deadline if self.deadline is not None else float("inf"),
        )
        cut: str | None = None
        stream = None
        try:
            with _interrupt_at(deadline):
                try:
                    stream = self.client.chat.completions.create(
                        **kwargs,
                        stream=True,
                        stream_options={"include_usage": True},
                    )
                except TypeError:
                    stream = self.client.chat.completions.create(**kwargs, stream=True)
                if first_limit:
                    _retarget_deadline(started + first_limit)
                for event in stream:
                    now = time.monotonic()
                    usage = getattr(event, "usage", None)
                    if usage:
                        inn = int(getattr(usage, "prompt_tokens", 0) or 0)
                        out = int(getattr(usage, "completion_tokens", 0) or 0)
                    if not event.choices:
                        if first_token_at is None and first_limit and now - started >= first_limit:
                            cut = "first_token"
                            break
                        continue
                    content, think = _delta_parts(event.choices[0].delta)
                    if think or content:
                        if first_token_at is None:
                            first_token_at = now
                            if speech_at is None and think_limit:
                                _retarget_deadline(started + think_limit)
                    if content:
                        if speech_at is None:
                            speech_at = now
                            _retarget_deadline(deadline)
                    if think:
                        think_parts.append(think)
                    if content:
                        content_parts.append(content)
                    if think and content and think == content:
                        if on_token:
                            on_token(content)
                    else:
                        if think and on_think:
                            on_think(think)
                        if content and on_token:
                            on_token(content)
                    if speech_at is None and think_limit and now - started >= think_limit:
                        cut = "think"
                        break
                    if first_token_at is None and first_limit and now - started >= first_limit:
                        cut = "first_token"
                        break
        except Exception as exc:
            if not (isinstance(exc, TimeoutError) or _timeout_like(exc)):
                raise
            text = "".join(content_parts) or "".join(think_parts)
            if not content_parts and think_parts:
                return LLMResult(
                    text=text,
                    input_tokens=inn,
                    output_tokens=out,
                    input_rate=self._in_rate,
                    output_rate=self._out_rate,
                    cut="think",
                )
            return LLMResult(
                text=text,
                input_tokens=inn,
                output_tokens=out,
                input_rate=self._in_rate,
                output_rate=self._out_rate,
                error=f"{type(exc).__name__}: {exc}"[:200],
                cut=None if content_parts else "first_token",
            )
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        text = "".join(content_parts) or "".join(think_parts)
        if cut == "first_token" and not text.strip():
            return LLMResult(
                text="",
                input_tokens=inn,
                output_tokens=out,
                input_rate=self._in_rate,
                output_rate=self._out_rate,
                error=f"no tokens after {first_limit:.0f}s",
                cut=cut,
            )
        if not text.strip():
            raise RuntimeError("empty stream")
        return LLMResult(
            text=text,
            input_tokens=inn,
            output_tokens=out,
            input_rate=self._in_rate,
            output_rate=self._out_rate,
            cut=cut,
        )


@contextmanager
def _interrupt_at(deadline: float):
    """Interrupt a blocked streaming read at an absolute monotonic deadline."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("model call deadline reached")
    previous = signal.getsignal(signal.SIGALRM)

    def expire(_signum, _frame):
        raise TimeoutError("model stream stopped yielding before its deadline")

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _retarget_deadline(when: float) -> None:
    """Shorten the live SIGALRM so a hang after first think cannot sit out the full call."""
    if threading.current_thread() is not threading.main_thread():
        return
    left = when - time.monotonic()
    if left <= 0:
        raise TimeoutError("model stream stopped yielding before its deadline")
    signal.setitimer(signal.ITIMER_REAL, left)


def _delta_parts(delta: Any) -> tuple[str, str]:
    if delta is None:
        return "", ""
    content = getattr(delta, "content", None) or ""
    think = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None) or ""
    extra = getattr(delta, "model_extra", None) or {}
    if isinstance(extra, dict):
        think = think or extra.get("reasoning") or extra.get("reasoning_content") or ""
    return str(content), str(think)


# Back-compat name used in older docs/tests.
XaiLLM = ChatLLM


@dataclass
class ScriptedLLM(LLM):
    """Deterministic stand-in. Optional per-call overrides via `scripts`."""

    preserve_member_order = True
    scripts: list[dict[str, Any]] = field(default_factory=list)
    i: int = 0

    def complete(
        self,
        *,
        system: str,
        user: str,
        on_token=None,
        on_think=None,
        prefix: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        if self.i < len(self.scripts):
            payload = self.scripts[self.i]
            self.i += 1
            text = json.dumps(payload)
            if on_token:
                on_token(text)
            return LLMResult(text=text, input_tokens=10, output_tokens=10, input_rate=0, output_rate=0)
        payload = {
            "speech": "I attend.",
            "nominate": None,
            "vote_election": None,
            "impeach": False,
            "propose": None,
            "vote_motion": None,
            "executive": None,
        }
        text = json.dumps(payload)
        if on_token:
            on_token(text)
        return LLMResult(text=text, input_tokens=10, output_tokens=10, input_rate=0, output_rate=0)


def extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    for tag in ("think", "reasoning", "thought"):
        text = re.sub(rf"<{tag}>.*?</{tag}>", "", text, flags=re.DOTALL | re.I)
    if "```" in text:
        fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.I)
        if fenced:
            text = fenced[-1].strip()
    decoder = json.JSONDecoder()
    last_err: Exception | None = None
    i = 0
    while True:
        start = text.find("{", i)
        if start < 0:
            break
        try:
            obj, _end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            last_err = exc
            i = start + 1
            continue
        if isinstance(obj, dict):
            return obj
        i = start + 1
    salvaged = salvage_act(text)
    if salvaged.get("speech") or salvaged.get("nominate") or salvaged.get("vote_election"):
        return salvaged
    raise ValueError(f"no JSON object in model output: {last_err or 'none'}")


def salvage_act(text: str) -> dict[str, Any]:
    """Pull speech/nominate/vote out of truncated or half-written JSON."""
    act: dict[str, Any] = {
        "speech": "",
        "nominate": None,
        "vote_election": None,
        "impeach": False,
        "propose": None,
        "vote_motion": None,
        "executive": None,
    }
    if not text:
        return act
    spoken = growing_speech(text) or planned_speech(text)
    if spoken:
        act["speech"] = spoken[:400]
    mid = re.search(r'"nominate"\s*:\s*\{\s*"member"\s*:\s*"([a-z][a-z0-9_-]{0,31})"', text)
    plat = re.search(r'"platform"\s*:\s*"((?:\\.|[^"\\])*)"', text)
    if mid:
        act["nominate"] = {"member": mid.group(1), "platform": plat.group(1) if plat else ""}
    ev = re.search(r'"vote_election"\s*:\s*"([a-z][a-z0-9_-]{0,31})"', text)
    if ev:
        act["vote_election"] = ev.group(1)
    if not act.get("vote_election"):
        spoken_vote = re.search(
            r"\bvote\w*\s+for\s+([a-z][a-z0-9_-]{0,31})\b", text, re.I
        )
        if spoken_vote:
            pick = as_member_id(spoken_vote.group(1))
            if pick:
                act["vote_election"] = pick
    impeach = re.search(
        r'"impeach"\s*:\s*(?:true|"(\d{3})"|(0|[1-9]\d{2,}))',
        text,
        re.I,
    )
    if impeach:
        act["impeach"] = impeach.group(1) or impeach.group(2) or True
    vm = re.search(
        r'"vote_motion"\s*:\s*"(aye|nay|abstain|yes|no|yea|against)"',
        text,
        re.I,
    )
    if vm:
        raw = vm.group(1).lower()
        act["vote_motion"] = {"yes": "aye", "yea": "aye", "no": "nay", "against": "nay"}.get(raw, raw)
    return act


def apply_prefix(prefix: str | None, text: str) -> str:
    """Glue an assistant prefill onto a continuation. Do not double a full object."""
    text = text or ""
    if not prefix:
        return text
    if text.startswith(prefix) or text.lstrip().startswith("{"):
        return text
    return prefix + text


def _seeded_on_token(on_token, prefix: str | None):
    if not on_token:
        return None
    if not prefix:
        return on_token
    sent = {"n": False}

    def hook(piece: str) -> None:
        if not sent["n"]:
            on_token(prefix)
            sent["n"] = True
        if piece:
            on_token(piece)

    return hook


_SPEECH_KEY = re.compile(r'"speech"\s*:\s*"')
_PLANNED_SPEECH = re.compile(
    r'(?:craft(?:ing)? speech|speech\s*(?:is|should be)?|chamber remarks)\s*[:\-]\s*"((?:\\.|[^"\\]){12,400})"',
    re.I,
)


def protocol_speech(speech: str) -> bool:
    """True when the chamber line is planning notes, not remarks."""
    s = (speech or "").strip().lower()
    if not s:
        return False
    cues = (
        "we need to output json",
        "we need to produce a json",
        "we need to produce json",
        "output json with",
        "output a json",
        "produce a json object",
        "we must output",
        "let's produce",
        "let's parse",
        "let's examine",
        "let's reconstruct",
        "we must preflight",
        "we need to infer",
        "we must first understand current state",
        "understand current state",
        "from the history",
        "we have a long history",
        "parse the given history",
        "parse the history",
        "we have acts t",
        "we are in turn",
        "the user is ",
        "current phase, open motion",
        "we need to decide what action",
    )
    if any(cue in s for cue in cues):
        return True
    if re.search(r"\bt\d+\s*:", s) and any(
        tok in s for tok in ("nominat", "host", "history", "ballot", "speech:")
    ):
        return True
    if s.count("\n") >= 3 and ("json" in s or "let's" in s or "we need" in s):
        return True
    return False


def fulfill_speech(
    act: dict[str, Any],
    *,
    member_id: str,
    president: bool = False,
) -> dict[str, Any]:
    """Fill vote/nominate/party/exec when speech already announced them."""
    speech = str(act.get("speech") or "")
    if not speech:
        return act
    if protocol_speech(speech):
        return act
    low = speech.lower()

    if not act.get("nominate") and not re.search(
        r"\b(decline to nominate|will not nominate|not nominate|no nomination)\b", low
    ):
        nom = re.search(
            r"\bnominat(?:e|es|ed|ing)\s+(myself|me|[a-z][a-z0-9_-]{0,31})\b",
            speech,
            re.I,
        )
        if nom:
            token = nom.group(1).lower()
            who = member_id if token in {"myself", "me"} else token
            if as_member_id(who):
                act["nominate"] = {"member": who, "platform": speech[:240]}

    if not act.get("vote_motion"):
        vm = re.search(
            r"\bvote\w*\s+(aye|yea|yes|nay|no|against|abstain)\b"
            r"|\b(aye|nay)\s+on\b"
            r"|\b(oppose|reject)\s+(?:the\s+)?(?:motion|bill|proposal)\b",
            speech,
            re.I,
        )
        if vm:
            token = (vm.group(1) or vm.group(2) or vm.group(3) or "").lower()
            act["vote_motion"] = {
                "aye": "aye",
                "yea": "aye",
                "yes": "aye",
                "nay": "nay",
                "no": "nay",
                "against": "nay",
                "oppose": "nay",
                "reject": "nay",
                "abstain": "abstain",
            }.get(token, token)

    if not act.get("vote_election") and not re.search(
        r"\b(will not vote|withhold|decline to vote|not vote for)\b", low
    ):
        ev = re.search(r"\bvote\w*\s+for\s+([a-z][a-z0-9_-]{0,31})\b", speech, re.I)
        if ev:
            pick = as_member_id(ev.group(1))
            if pick:
                act["vote_election"] = pick

    if act.get("party") is None:
        leave = re.search(r"\bleave\s+(?:my\s+)?party\b", speech, re.I)
        join = re.search(
            r"\b(?:join|found|form)\s+(?:the\s+)?([a-z][a-z0-9_-]{0,31})\s+party\b",
            speech,
            re.I,
        )
        if leave:
            act["party"] = "none"
        elif join:
            act["party"] = join.group(1).lower()

    if not as_impeach(act.get("impeach"))[0]:
        future = re.search(
            r"\b(?:will|going to)\s+impeach\b|\bimpeach(?:ing)?\s+next\b",
            low,
        )
        if not future:
            cited = re.search(
                r"\b(?:impeach(?:e[ds]|ing)?|mark impeach)\b[\s\S]{0,80}?\b(\d{3})\b"
                r"|\b(\d{3})\b[\s\S]{0,40}?\bimpeach",
                speech,
                re.I,
            )
            if cited:
                art = cited.group(1) or cited.group(2)
                if art and int(art) >= 200:
                    act["impeach"] = art
            elif re.search(r"\bimpeach(?:e[ds]|ing)?\b", low) and re.search(
                r"\b(207|empty|no goal|fail(?:ing|ed)? to set|privileges|workspace)\b",
                low,
            ):
                act["impeach"] = "207"

    if president and not act.get("executive"):
        if not re.search(r"\bimpeach", low) and not re.search(
            r"fail(?:ing|ed)?\s+to\s+set(?:\s+a)?\s+goal", low
        ):
            goal = re.search(
                r"(?:set|enact|establish|declare)\s+goal(?:\s+|:)(?P<body>(?!s\b).+)",
                speech,
                re.I | re.S,
            )
            if goal:
                text = " ".join(goal.group("body").split())[:800]
                if text and not re.match(r"and\b", text, re.I):
                    from adags.effects import complete_set_goal

                    fx = complete_set_goal({"type": "set_goal", "text": text}, speech=speech)
                    if str(fx.get("id") or "").lower() == "speech-goal":
                        fx["id"] = "goal1"
                    if fx.get("text"):
                        act["executive"] = [fx]
    return act


def planned_speech(text: str) -> str:
    """Chamber line drafted in prose, e.g. Let's craft speech: \"I vote aye…\"."""
    last = ""
    for match in _PLANNED_SPEECH.finditer(text or ""):
        last = match.group(1)
    return last[:400]


def growing_speech(buf: str) -> str:
    """Public speech so far in a (possibly truncated) JSON act.

    Uses the last `"speech": "` so a planning draft is replaced by the real
    chamber line. Incomplete escapes wait for more tokens.
    """
    last = None
    for match in _SPEECH_KEY.finditer(buf or ""):
        last = match
    if last is None:
        return ""
    return _decode_json_string_prefix(buf[last.end() :])


def _decode_json_string_prefix(body: str) -> str:
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == '"':
            break
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= n:
            break
        nxt = body[i + 1]
        simple = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
        if nxt in simple:
            out.append(simple[nxt])
            i += 2
            continue
        if nxt == "u":
            hexpart = body[i + 2 : i + 6]
            if len(hexpart) < 4:
                break
            if all(c in "0123456789abcdefABCDEF" for c in hexpart):
                out.append(chr(int(hexpart, 16)))
                i += 6
                continue
            break
        i += 2
    return "".join(out)


def resolve_provider(name: str | None = None) -> str:
    raw = (name or os.environ.get("ADAGS_PROVIDER") or "").strip().lower()
    if raw in {"nous", "portal"}:
        return "hermes"
    if raw:
        return raw
    return "hermes"


def make_llm(*, provider: str | None = None, model: str | None = None) -> LLM:
    name = resolve_provider(provider)
    if name == "mock":
        return ScriptedLLM()
    if name == "hermes":
        ep = endpoint(model=model)
        return ChatLLM(
            model=ep["model"],
            api_key=ep["api_key"],
            base_url=ep["base_url"],
            json_mode=False,
            rates=(0.0, 0.0),
        )
    if name not in PROVIDERS:
        raise RuntimeError(
            f"unknown provider {name!r}; choose hermes, {', '.join(PROVIDERS)}"
        )
    spec = PROVIDERS[name]
    key = os.environ.get(spec["key_env"])
    if not key:
        raise RuntimeError(
            f"{spec['key_env']} is not set. For a $0 run: get a key at "
            "https://openrouter.ai/keys and `export OPENROUTER_API_KEY=...`"
        )
    chosen = model or os.environ.get("ADAGS_MODEL") or spec["default_model"]
    headers = None
    if name == "openrouter":
        headers = {
            "HTTP-Referer": os.environ.get("ADAGS_REFERER", "https://github.com/adags"),
            "X-Title": "ADAGS",
        }
    return ChatLLM(
        model=chosen,
        api_key=key,
        base_url=os.environ.get("ADAGS_BASE_URL") or spec["base_url"],
        extra_headers=headers,
    )

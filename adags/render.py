"""Terminal rendering for the operator harness."""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
from pathlib import Path

from adags.constitution import apply_to_runtime
from adags.gov import president_id
from adags.llm import growing_speech
from adags.state import RunState


def collapse_ws(text: str) -> str:
    """One paragraph. Live view and previews must not replay model newlines."""
    return re.sub(r"\s+", " ", text or "").strip()


class FlowPrinter:
    """One wrapped paragraph. `show(full)` prints only the new tail."""

    def __init__(self, *, indent: str = "│ ", width: int | None = None, write=None) -> None:
        self.indent = indent
        if width is None:
            width = shutil.get_terminal_size((80, 24)).columns
        self.width = max(len(indent) + 16, int(width))
        self._write = write or (lambda s: print(s, end="", flush=True))
        self.shown = ""
        self.word = ""
        self.col = 0
        self.started = False
        self._space = False

    def show(self, text: str) -> None:
        if not text:
            return
        if not text.startswith(self.shown):
            self._reset_line()
        delta = text[len(self.shown) :]
        for ch in delta:
            self._emit(ch)
        self.shown = text

    def finish(self) -> bool:
        self._flush_word()
        if self.started:
            self._write("\n")
        return self.started

    def _reset_line(self) -> None:
        self._flush_word()
        if self.started:
            self._write("\n")
        self.shown = ""
        self.word = ""
        self.col = 0
        self.started = False
        self._space = False

    def _emit(self, ch: str) -> None:
        if ch == " ":
            self._flush_word()
            self._space = True
            return
        self.word += ch

    def _flush_word(self) -> None:
        if not self.word:
            return
        pad = 1 if self._space and self.started and self.col > len(self.indent) else 0
        room = self.width - (self.col if self.started else len(self.indent))
        if self.started and pad + len(self.word) > room:
            self._write("\n" + self.indent)
            self.col = len(self.indent)
            pad = 0
        if not self.started:
            self._write(self.indent)
            self.col = len(self.indent)
            self.started = True
        if pad:
            self._write(" ")
            self.col += 1
        self._write(self.word)
        self.col += len(self.word)
        self.word = ""
        self._space = False


class SpeechPrinter:
    """Live view: public speech only, one wrapped paragraph."""

    def __init__(self, *, indent: str = "│ ", width: int | None = None, write=None) -> None:
        self.buf = ""
        self.flow = FlowPrinter(indent=indent, width=width, write=write)

    @property
    def started(self) -> bool:
        return self.flow.started

    @property
    def shown(self) -> str:
        return self.flow.shown

    def feed(self, piece: str) -> None:
        if not piece:
            return
        self.buf += piece
        self.flow.show(visible_speech(self.buf))

    def finish(self) -> bool:
        return self.flow.finish()


def visible_speech(buf: str) -> str:
    """Chamber line only. Drop a lone `{{` the model emits after the prefill."""
    text = collapse_ws(growing_speech(buf))
    while text.startswith("{"):
        text = collapse_ws(text[1:])
    return text


_BALLOT_ALIAS = {
    "aye": "aye",
    "yes": "aye",
    "yea": "aye",
    "yay": "aye",
    "for": "aye",
    "nay": "nay",
    "no": "nay",
    "against": "nay",
    "oppose": "nay",
    "opposed": "nay",
    "abstain": "abstain",
    "present": "abstain",
}


def as_ballot(value) -> str | None:
    if isinstance(value, str):
        return _BALLOT_ALIAS.get(value.strip().lower())
    if isinstance(value, dict):
        for key in ("vote", "choice", "ballot", "vote_motion"):
            found = as_ballot(value.get(key))
            if found:
                return found
        for key in ("aye", "nay", "abstain"):
            if value.get(key) is True:
                return key
        for key, mapped in _BALLOT_ALIAS.items():
            if value.get(key) is True:
                return mapped
    return None


def json_scaffold(buf: str) -> bool:
    """True when content is only the JSON wrapper, not notes or speech."""
    compact = re.sub(r"\s+", "", buf or "")
    return compact in {
        "",
        "{",
        '{"',
        '{"speech"',
        '{"speech":',
        '{"speech":"',
    }


class ChamberVoice:
    """Collapsed thinking (one dim line) until `"speech"` takes the floor."""

    def __init__(
        self,
        *,
        indent: str = "│ ",
        think_indent: str = "┆ ",
        width: int | None = None,
        write=None,
        interval: float = 0.5,
    ) -> None:
        self._write = write or (lambda s: print(s, end="", flush=True))
        self.indent = indent
        self.think_indent = think_indent
        self.printer = SpeechPrinter(indent=indent, width=width, write=self._write)
        self.chars = 0
        self.think_chars = 0
        self.interval = interval
        self._t0 = time.monotonic()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status_len = 0
        self._think_open = False
        self._thought_done = False
        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()

    def status_text(self) -> str:
        elapsed = time.monotonic() - self._t0
        if self._think_open or self.think_chars:
            return c("2", f"{self.think_indent}thinking  {elapsed:.0f}s")
        if self.chars:
            return c("2", f"{self.indent}backend  {elapsed:.0f}s · {self.chars} chars, no speech yet")
        return c("2", f"{self.indent}backend  {elapsed:.0f}s · waiting on model")

    def feed(self, piece: str) -> None:
        with self._lock:
            self.chars += len(piece or "")
            upcoming = visible_speech(self.printer.buf + (piece or ""))
            if upcoming:
                if not self.printer.started:
                    self._end_think()
                self.printer.feed(piece)
                return
            self.printer.feed(piece)
            if not json_scaffold(self.printer.buf):
                self._emit_think(piece)

    def feed_think(self, piece: str) -> None:
        with self._lock:
            if self.printer.started:
                return
            self._emit_think(piece)

    def finish(self) -> bool:
        self._stop.set()
        self._thread.join(timeout=1.0)
        with self._lock:
            spoke = self.printer.started
            if spoke:
                self._end_think()
                return self.printer.finish()
            if self._think_open:
                self._end_think()
            else:
                self._clear()
                self._write("\n")
            return False

    def _emit_think(self, piece: str) -> None:
        if not piece or self.printer.started or self._thought_done:
            return
        self.think_chars += len(piece)
        self._think_open = True
        self._paint(self.status_text())

    def _end_think(self) -> None:
        if self._thought_done:
            return
        if not self._think_open:
            self._clear()
            return
        elapsed = time.monotonic() - self._t0
        self._paint(c("2", f"{self.think_indent}thought  {elapsed:.0f}s"))
        self._write("\n")
        self._status_len = 0
        self._think_open = False
        self._thought_done = True

    def _tick(self) -> None:
        self._pulse()
        while not self._stop.wait(self.interval):
            self._pulse()

    def _pulse(self) -> None:
        with self._lock:
            if self.printer.started or self._thought_done:
                return
            self._paint(self.status_text())

    def _paint(self, msg: str) -> None:
        width = shutil.get_terminal_size((80, 24)).columns
        pad = max(0, max(self._status_len, width) - len(msg))
        self._write("\r" + msg + (" " * pad))
        self._status_len = max(len(msg), width)

    def _clear(self) -> None:
        if self._status_len:
            self._write("\r" + (" " * self._status_len) + "\r")
            self._status_len = 0


def _color() -> bool:
    if os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE"):
        return True
    if os.environ.get("NO_COLOR"):
        return False
    return bool(os.isatty(1))


def c(code: str, text: str) -> str:
    if not _color():
        return text
    return f"\033[{code}m{text}\033[0m"


# Distinct 256-color faces. A slug always maps to the same index.
_PARTY_FG = (
    208,  # orange
    39,  # blue
    171,  # magenta
    114,  # green
    220,  # gold
    204,  # pink
    73,  # teal
    141,  # violet
    215,  # peach
    75,  # sky
    186,  # olive
    167,  # rose
    99,  # purple
    45,  # aqua
    178,  # amber
    69,  # steel
)


def party_fg(slug: str) -> int:
    h = 2166136261
    for byte in (slug or "").encode("utf-8"):
        h ^= byte
        h = (h * 16777619) & 0xFFFFFFFF
    return _PARTY_FG[h % len(_PARTY_FG)]


def c256(n: int, text: str, *, bold: bool = False) -> str:
    if not _color():
        return text
    code = f"1;38;5;{n}" if bold else f"38;5;{n}"
    return f"\033[{code}m{text}\033[0m"


def member_parties(members: list[dict] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for member in members or []:
        slug = str(member.get("party") or "").strip()
        mid = str(member.get("id") or "").strip()
        if slug and mid:
            out[mid] = slug
    return out


def paint_party(slug: str, *, chip: bool = True) -> str:
    if not slug:
        return ""
    face = c256(party_fg(slug), slug, bold=True)
    if not chip:
        return face
    return f"{c256(party_fg(slug), '●')} {face}"


def paint_citizen(member_id: str, party: str | None = None, *, bold: bool = False) -> str:
    if not party:
        return c("1", member_id) if bold else member_id
    return c256(party_fg(party), member_id, bold=bold)


def format_roster(roster: dict[str, list[str]]) -> str:
    parts = []
    for name, ids in sorted(roster.items()):
        people = ", ".join(paint_citizen(i, name) for i in ids)
        parts.append(f"{paint_party(name)} ({people})")
    return "; ".join(parts)


def term_width() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def rule(width: int | None = None) -> str:
    n = min(width or term_width(), 72)
    return c("2", "─" * n)


def act_marks(
    act: dict,
    *,
    phase: str | None = None,
    seated: list[str] | None = None,
) -> list[str]:
    """Chamber marks the host will honor. Wrong-phase acts are marked ignored."""
    from adags.gov import as_impeach, as_member_id

    marks: list[str] = []
    seated_set = set(seated or [])
    usage = act.get("_usage") or {}
    if usage.get("error"):
        err = collapse_ws(str(usage["error"]))[:100]
        marks.append(f"timeout · {err}" if "timeout" in err.lower() else f"error · {err}")
    if usage.get("parse_error"):
        n = len(usage.get("raw") or "")
        marks.append(f"no valid act · {n} chars raw" if n else "no valid act")
    nom = act.get("nominate")
    who = None
    if isinstance(nom, dict):
        who = as_member_id(nom.get("member")) or as_member_id(nom)
    if who:
        if phase is None or (phase == "nominate" and (not seated_set or who in seated_set)):
            marks.append(f"nominates {who}")
        else:
            why = "not seated" if phase == "nominate" else phase
            marks.append(f"ignored nominate ({why})")
    vote = as_member_id(act.get("vote_election"))
    if vote:
        if phase is None or phase == "ballot":
            marks.append(f"votes {vote}")
        else:
            marks.append(f"ignored vote ({phase})")
    marked, article = as_impeach(act.get("impeach"))
    if marked:
        marks.append(f"impeach {article}" if article else "impeach")
    if act.get("party") is not None:
        from adags.gov import as_party_id

        slug = as_party_id(act.get("party"))
        if slug:
            marks.append(f"joins {slug}")
        elif slug == "":
            marks.append("leaves party")
    prop = act.get("propose")
    if isinstance(prop, dict) and (prop.get("title") or prop.get("text") or prop.get("effects")):
        from adags.effects import bill_title, propose_effects

        title = bill_title(
            title=str(prop.get("title") or ""),
            text=str(prop.get("text") or ""),
            effects=prop.get("effects") or propose_effects(prop),
            speech=str(act.get("speech") or ""),
        )
        marks.append(f"proposes {title}")
    vm = as_ballot(act.get("vote_motion"))
    if vm:
        marks.append(f"{vm} on the motion")
    if act.get("executive"):
        marks.append("executive")
    raw_w = act.get("whisper")
    if isinstance(raw_w, dict):
        who = as_member_id(raw_w.get("to") or raw_w.get("member"))
        if who:
            marks.append(f"whispers {who}")
    elif isinstance(raw_w, str) and raw_w.strip() and raw_w.strip().lower() not in {"null", "none"}:
        marks.append("whispers")
    return marks


def paint_mark(mark: str, *, parties: dict[str, str] | None = None) -> str:
    if mark.startswith("joins "):
        return f"joins {paint_party(mark[6:])}"
    if mark.startswith("nominates ") or mark.startswith("votes ") or mark.startswith("whispers "):
        verb, _, who = mark.partition(" ")
        color = "35" if verb == "whispers" else "36"
        return f"{c(color, verb)} {paint_citizen(who, (parties or {}).get(who))}"
    if mark.startswith("aye"):
        return c("32", mark)
    if (
        mark in {"impeach", "timeout", "error", "no valid act"}
        or mark.startswith("impeach")
        or mark.startswith("nay")
        or mark.startswith("timeout")
        or mark.startswith("error")
        or mark.startswith("no valid act")
    ):
        return c("31", mark)
    if mark.startswith("proposes"):
        return c("33", mark)
    if mark.startswith("ignored"):
        return c("2", mark)
    return mark


def format_votes(votes: dict | None, parties: dict[str, str] | None = None) -> str:
    votes = votes or {}
    if not votes:
        return "no votes yet"
    buckets: dict[str, list[str]] = {}
    for who, how in votes.items():
        buckets.setdefault(str(how), []).append(str(who))

    def names(ids: list[str]) -> str:
        return ", ".join(paint_citizen(i, (parties or {}).get(i)) for i in ids)

    parts = []
    for how in ("aye", "nay", "abstain"):
        if how in buckets:
            parts.append(f"{how} {names(buckets.pop(how))}")
    for how, who in buckets.items():
        parts.append(f"{how} {names(who)}")
    return " · ".join(parts)


def motion_label(motion: dict | None) -> str:
    from adags.effects import bill_title

    if not motion:
        return "(no bill)"
    return bill_title(
        title=str(motion.get("title") or ""),
        text=str(motion.get("text") or ""),
        effects=motion.get("effects"),
    )


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_width(text: str) -> int:
    return len(_ANSI_RE.sub("", text or ""))


def wrap_field(
    label: str,
    text: str,
    *,
    width: int | None = None,
    atom: str | None = None,
) -> list[str]:
    width = width or term_width()
    pad = f"  {label:<9} "
    inner = max(20, width - visible_width(pad))
    if atom:
        chunks = [part.strip() for part in (text or "").split(atom) if part.strip()]
        glue = atom
    else:
        chunks = collapse_ws(text).split()
        glue = " "
    if not chunks:
        return [pad + "—"]
    lines: list[str] = []
    cur = chunks[0]
    for chunk in chunks[1:]:
        trial = cur + glue + chunk
        if visible_width(trial) <= inner:
            cur = trial
        else:
            lines.append(cur)
            cur = chunk
    lines.append(cur)
    hang = " " * visible_width(pad)
    return [pad + lines[0], *[hang + line for line in lines[1:]]]


def emit(text: str = "") -> None:
    print(text, flush=True)


def turn_open(
    *,
    turn: int,
    gov: dict,
    n_members: int,
    motion: dict | None,
    members: list[dict] | None = None,
) -> None:
    emit()
    emit(rule())
    parties = member_parties(members)
    prez = president_id(gov) or "vacant"
    emit(
        f"{c('1', f'turn {turn}')}  ·  {gov.get('election_phase')}  ·  "
        f"president {paint_citizen(prez, parties.get(prez), bold=True)}  ·  "
        f"{n_members} seated"
    )
    from adags.gov import party_roster

    roster = party_roster(members or [])
    if roster:
        for line in wrap_field("parties", format_roster(roster), atom="; "):
            emit(line)
    from adags.gov import format_party_tickets

    tickets = format_party_tickets(gov)
    if tickets != "(none)":
        for line in wrap_field("tickets", tickets):
            emit(line)
    noms = gov.get("nominees") or []
    if noms:
        named = ", ".join(
            paint_citizen(n.get("member", "?"), parties.get(n.get("member", "")))
            for n in noms
        )
        for line in wrap_field("nominees", named):
            emit(line)
    if motion:
        for line in wrap_field("bill", motion_label(motion)):
            emit(line)
        for line in wrap_field("votes", format_votes(motion.get("votes"), parties)):
            emit(line)
    emit(rule())


def citizen_open(member_id: str, *, party: str | None = None) -> None:
    emit()
    if party:
        emit(f"{paint_citizen(member_id, party, bold=True)}  {paint_party(party)}")
    else:
        emit(c("1", member_id))


def citizen_close(
    act: dict,
    *,
    elapsed: float,
    spoke: bool,
    phase: str | None = None,
    seated: list[str] | None = None,
    parties: dict[str, str] | None = None,
) -> None:
    if not spoke:
        emit(c("2", "│ (silent)"))
    marks = act_marks(act, phase=phase, seated=seated)
    if not marks and not spoke:
        pass
    for mark in marks:
        emit(f"{c('2', '·')} {paint_mark(mark, parties=parties)}")
    emit(c("2", f"  {elapsed:.0f}s"))


def turn_close(
    *,
    turn: int,
    gov: dict,
    motion: dict | None,
    motion_notes: list[str],
    impeached: bool,
    seated: str | None,
    members: list[dict] | None = None,
) -> None:
    emit()
    emit(rule())
    parties = member_parties(members)
    prez = president_id(gov) or "vacant"
    emit(
        f"closed  ·  turn {turn}  ·  president {paint_citizen(prez, parties.get(prez), bold=True)}  ·  "
        f"next {gov.get('election_phase')}"
    )
    if impeached:
        emit(c("31", "  office vacated"))
    if seated:
        emit(c("32", f"  seated {paint_citizen(seated, parties.get(seated))} as president"))
    noms = gov.get("nominees") or []
    if noms:
        named = ", ".join(
            paint_citizen(n.get("member", "?"), parties.get(n.get("member", "")))
            for n in noms
        )
        for line in wrap_field("nominees", named):
            emit(line)
    if motion:
        for line in wrap_field("bill", motion_label(motion)):
            emit(line)
        for line in wrap_field("votes", format_votes(motion.get("votes"), parties)):
            emit(line)
    for note in motion_notes:
        for line in wrap_field("motion", note):
            emit(line)
    emit(rule())


def banner(state: RunState) -> str:
    if not state.path("control.json").exists():
        return c("1", "ADAGS") + "  (no run — /init)"
    ctl = state.control()
    gov = apply_to_runtime(state.gov(), state.law())
    prez = president_id(gov) or "vacant"
    parties = member_parties(state.members()) if state.path("members.json").exists() else {}
    wait = f"  {c('33', 'waiting')}" if ctl.get("paused") else ""
    return (
        f"{c('1', 'ADAGS')}  {state.root.name}  "
        f"turn {ctl['turn']}  "
        f"{gov.get('election_phase')}  "
        f"president {paint_citizen(prez, parties.get(prez), bold=True)}"
        f"{wait}"
    )


def status_block(state: RunState) -> str:
    if not state.path("control.json").exists():
        return "no run in this directory.  /init to found one."
    ctl = state.control()
    gov = apply_to_runtime(state.gov(), state.law())
    members = state.members()
    prez = (gov.get("offices") or {}).get("president") or {}
    goals = state.goals()
    lines = [banner(state)]
    parties = member_parties(members)
    lines.extend(
        wrap_field(
            "seated",
            ", ".join(paint_citizen(m["id"], parties.get(m["id"])) for m in members),
        )
    )
    lines.extend(
        wrap_field(
            "term",
            f"start {prez.get('term_start')} · length {gov.get('term_length')} · "
            f"election {gov.get('election_enabled')}",
        )
    )
    noms = gov.get("nominees") or []
    if noms:
        lines.extend(
            wrap_field(
                "nominees",
                ", ".join(
                    paint_citizen(n.get("member", "?"), parties.get(n.get("member", "")))
                    for n in noms
                ),
            )
        )
    from adags.gov import party_roster

    roster = party_roster(members)
    if roster:
        lines.extend(wrap_field("parties", format_roster(roster), atom="; "))
    from adags.gov import format_party_tickets

    tickets = format_party_tickets(gov)
    if tickets != "(none)":
        lines.extend(wrap_field("tickets", tickets))
    if goals:
        for gid, text in goals.items():
            lines.extend(wrap_field(str(gid), text))
    else:
        lines.extend(wrap_field("goal", "none"))
    open_m = state.root / "motions" / "open.json"
    if open_m.exists():
        import json

        mot = json.loads(open_m.read_text(encoding="utf-8"))
        lines.extend(wrap_field("bill", motion_label(mot)))
        lines.extend(wrap_field("votes", format_votes(mot.get("votes"), parties)))
    return "\n".join(lines)


def journal_tail(state: RunState, n: int = 2) -> str:
    p = state.path("journal.md")
    if not p.exists():
        return "(no journal)"
    text = p.read_text(encoding="utf-8")
    chunks = [c for c in text.split("\n## Turn ") if c.strip() and not c.startswith("# Journal")]
    if not chunks:
        return text.strip() or "(empty journal)"
    take = chunks[-n:]
    out = []
    for i, chunk in enumerate(take):
        # first line of a split chunk is the turn number
        out.append("## Turn " + chunk.strip())
    return "\n\n".join(out)


def digest_text(state: RunState) -> str:
    p = state.path("digest.md")
    if not p.exists():
        return "(no digest)"
    return p.read_text(encoding="utf-8").rstrip()


def members_text(state: RunState) -> str:
    gov = state.gov() if state.path("gov.json").exists() else {}
    prez = president_id(gov)
    lines = []
    for m in state.members():
        star = " *" if m["id"] == prez else "  "
        slug = str(m.get("party") or "").strip()
        name = paint_citizen(m["id"], slug or None, bold=m["id"] == prez)
        pad = " " * max(1, 12 - len(m["id"]))
        tag = f"{paint_party(slug)}  " if slug else ""
        values = (m.get("values") or "").replace("\n", " ")
        if len(values) > 90:
            values = values[:87] + "…"
        lines.append(f"{star}{name}{pad}  {tag}{values}")
    return "\n".join(lines) or "(no members)"


def goals_text(state: RunState) -> str:
    p = state.path("goals.md")
    if not p.exists():
        return "(no goals file)"
    return p.read_text(encoding="utf-8").rstrip()


def law_text(state: RunState) -> str:
    return state.constitution().rstrip()


def suggestions_text(state: RunState) -> str:
    box = state.root / "suggestions"
    files = sorted(box.glob("*.md")) if box.exists() else []
    if not files:
        return "(suggestion box empty)"
    return "\n\n".join(p.read_text(encoding="utf-8").rstrip() for p in files)


def doctor_text() -> str:
    rows = []

    def row(ok: bool, label: str, detail: str) -> None:
        mark = c("32", "ok") if ok else c("31", "no")
        rows.append(f"  {mark}  {label:16} {detail}")

    hermes = shutil.which(os.environ.get("ADAGS_HERMES_BIN", "hermes"))
    row(bool(hermes), "hermes", hermes or "not on PATH")
    codex = shutil.which(os.environ.get("ADAGS_CODEX_BIN", "codex"))
    row(bool(codex), "codex", (codex + f"  brief={os.environ.get('ADAGS_BRIEF_MODEL', 'gpt-5.6-luna')}") if codex else "not on PATH")
    row(bool(os.environ.get("OPENROUTER_API_KEY")), "openrouter", "OPENROUTER_API_KEY")
    row(bool(os.environ.get("XAI_API_KEY")), "xai", "XAI_API_KEY")
    row(bool(os.environ.get("OPENAI_API_KEY")), "openai", "OPENAI_API_KEY")
    from adags.llm import resolve_provider
    from adags.hermes_backend import resolve_model

    row(True, "provider", resolve_provider())
    row(True, "model", resolve_model())
    return "doctor\n" + "\n".join(rows)


REPL_HELP = """
commands  (leading / optional)

  status              snapshot of the run
  run [n]             play n turns (default 1); asking raises the turn cap
  pause / resume      freeze or unfreeze the clock
  journal [n]         last n journal turns (default 2)
  digest              last-turn digest
  law                 constitution
  goals               goal register
  members             seated citizens
  suggestions         host-facing suggestions from the polity
  veto                reverse last reversible act
  petition <text>     inject a bill
  doctor              keys, hermes, provider
  archive [label]     move this run to archive/ and found a new one
  init                found a run if missing
  help                this list
  quit                leave the harness
""".strip()

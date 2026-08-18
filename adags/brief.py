"""Occasional Luna clerk brief via `codex exec`. Not a citizen backend."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

BRIEF_SYSTEM = """You are the clerk of record for ADAGS, not a citizen and not a legislator.

Write a chamber brief of at most 220 words. Only what the host actually did:
who holds office; whether an election or impeachment happened; which files were
written and whether they have a body; which bills executed; which were already
law, reserved to the President, or empty; how many live goals sit on the
register; who is blocking whom.

Do not quote articles back. Do not recommend a new 30x. Do not recap every
speech. If the world did not change, say that in one sentence.
"""


def brief_every() -> int:
    raw = os.environ.get("ADAGS_BRIEF_EVERY", "4")
    try:
        return max(0, int(raw))
    except ValueError:
        return 4


def brief_model() -> str:
    return (os.environ.get("ADAGS_BRIEF_MODEL") or "gpt-5.6-luna").strip()


def due(turn: int) -> bool:
    n = brief_every()
    return n > 0 and int(turn) > 0 and int(turn) % n == 0


def recent_journal(text: str, *, turns: int = 4, each: int = 1600) -> str:
    blocks = re.split(r"(?=^## Turn \d+)", text or "", flags=re.M)
    chunks = [b.strip() for b in blocks if b.strip().startswith("## Turn")]
    picked = chunks[-turns:]
    return "\n\n".join(c[:each] for c in picked)


def extract_last_message(raw: str) -> str:
    """Best-effort last assistant message from `codex exec` text output."""
    text = (raw or "").strip()
    if not text:
        return ""
    for pat in (
        r"(?ms)^codex\s*\n(.+?)(?=\n^tokens used:|\Z)",
        r"(?ms)^assistant\s*\n(.+?)(?=\n^(?:user|tokens used:|\Z))",
    ):
        found = list(re.finditer(pat, text, re.I))
        if found:
            return found[-1].group(1).strip()
    return text[-2000:].strip()


def run_codex_brief(user: str, *, model: str | None = None, timeout: float = 45.0) -> str:
    binary = shutil.which(os.environ.get("ADAGS_CODEX_BIN", "codex"))
    if not binary:
        raise RuntimeError("codex CLI not on PATH")
    prompt = BRIEF_SYSTEM.strip() + "\n\nRECORD:\n" + (user or "").strip()
    out = Path(tempfile.mkdtemp(prefix="adags-brief-")) / "brief.txt"
    cwd = Path(tempfile.mkdtemp(prefix="adags-brief-cwd-"))
    cmd = [
        binary,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--color",
        "never",
        "-s",
        "read-only",
        "-m",
        model or brief_model(),
        "-C",
        str(cwd),
        "-o",
        str(out),
        prompt,
    ]
    subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd),
    )
    if out.exists():
        body = out.read_text(encoding="utf-8", errors="replace").strip()
        if body:
            return body[:2000]
    return ""


def maybe_clerk_brief(
    state,
    *,
    turn: int,
    mechanical: str,
    runner=None,
) -> str | None:
    if not due(turn):
        return None
    journal = ""
    path = state.path("journal.md")
    if path.exists():
        journal = recent_journal(path.read_text(encoding="utf-8", errors="replace"))
    user = (journal or mechanical or "").strip()
    if not user:
        return None
    fn = runner or run_codex_brief
    try:
        text = (fn(user) or "").strip()
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None
    if not text or len(text) < 40:
        return None
    return text[:2000]


def digest_for_card(digest: str, *, exclude_member: str | None = None) -> str:
    """Return prior chamber speech without repeating summaries or own memory."""
    text = digest or ""
    if "\n---\n" in text:
        # The mechanical digest follows the periodic clerk recap. Including both
        # repeats the same events in two forms.
        text = text.rsplit("\n---\n", 1)[1]
    marker = "## Speech\n"
    if marker not in text:
        return "(none)"
    text = text.split(marker, 1)[1]
    if "\nImpeach marks:" in text:
        text = text.split("\nImpeach marks:", 1)[0]
    if exclude_member:
        own = re.compile(
            rf"^\*\*{re.escape(exclude_member)}:\*\*.*?(?=^\*\*[^\n]+:\*\*|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        text = own.sub("", text)
    return text.strip()[-3200:] or "(none)"

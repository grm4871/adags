"""Addressed whips: recipient and operator see them; the floor does not."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adags.gov import as_member_id
from adags.llm import protocol_speech

WHISPER_LIMIT = 200
HOLD_FILE = "whisper_inbox.json"
LOG_FILE = "whispers.jsonl"


def parse_whisper(raw: Any, *, sender: str, seated: list[str]) -> dict | str | None:
    """Return {from,to,body}, an error string, or None if omitted."""
    if raw is None or raw is False:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text.lower() in {"null", "none"}:
            return None
        if ":" in text:
            dest, _, rest = text.partition(":")
            raw = {"to": dest.strip(), "body": rest.strip()}
        else:
            return "whisper ignored (need to and body)"
    if not isinstance(raw, dict):
        return "whisper ignored (need to and body)"
    target = as_member_id(raw.get("to") or raw.get("member") or raw.get("id"))
    body = str(raw.get("body") or raw.get("text") or raw.get("message") or "").strip()
    if not target:
        return "whisper ignored (need a seated recipient)"
    if target == sender:
        return "whisper ignored (self)"
    if target not in set(seated):
        return "whisper ignored (not seated)"
    if not body or protocol_speech(body):
        return "whisper ignored (empty or notes)"
    return {"from": sender, "to": target, "body": body[:WHISPER_LIMIT]}


def format_inbox(notes: list[dict] | None) -> str:
    if not notes:
        return ""
    lines = ["Whispers to you (private; the floor does not hear these):"]
    for note in notes:
        who = str(note.get("from") or "?")
        body = str(note.get("body") or "").strip()
        if body:
            lines.append(f"- {who}: {body}")
    return "\n".join(lines) if len(lines) > 1 else ""


def format_whisper_log(notes: list[dict] | None) -> str:
    if not notes:
        return "none"
    return ", ".join(
        f"{n.get('from', '?')}→{n.get('to', '?')}" for n in notes if n.get("to")
    )


def load_hold(root: Path) -> dict[str, list[dict]]:
    path = Path(root) / HOLD_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[dict]] = {}
    for mid, notes in data.items():
        if isinstance(notes, list):
            out[str(mid)] = [n for n in notes if isinstance(n, dict)]
    return out


def save_hold(root: Path, inbox: dict[str, list[dict]]) -> None:
    path = Path(root) / HOLD_FILE
    cleaned = {mid: list(notes) for mid, notes in inbox.items() if notes}
    if not cleaned:
        if path.exists():
            path.unlink()
        return
    path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")


def append_log(root: Path, turn: int, note: dict) -> None:
    path = Path(root) / LOG_FILE
    rec = {"turn": int(turn), **note}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

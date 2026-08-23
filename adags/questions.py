"""Questions: public interrogation routed to the target's next card."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LIMIT = 160
HOLD = "question_inbox.json"


def _path(root: Path) -> Path:
    return root / HOLD


def parse_question(raw: Any, *, sender: str, seated: list[str]) -> dict | str | None:
    """Return {to, body}, an error string, or None."""
    if raw is None or raw is False:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if ":" in text:
            dest, _, rest = text.partition(":")
            raw = {"to": dest.strip(), "body": rest.strip()}
        else:
            return "question ignored (need to and body)"
    if not isinstance(raw, dict):
        return "question ignored (need to and body)"
    from adags.gov import as_member_id

    target = as_member_id(raw.get("to") or raw.get("member"))
    body = str(raw.get("body") or raw.get("text") or "").strip()
    if not target or target not in set(seated):
        return "question ignored (need a seated recipient)"
    if target == sender:
        return "question ignored (self)"
    if not body:
        return "question ignored (empty)"
    return {"from": sender, "to": target, "body": body[:LIMIT]}


def load_hold(root: Path) -> dict[str, list[dict]]:
    p = _path(root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_hold(root: Path, data: dict[str, list[dict]]) -> None:
    _path(root).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def format_inbox(notes: list[dict] | None) -> str:
    if not notes:
        return ""
    lines = ["Questions you must answer this turn (public record):"]
    for q in notes:
        lines.append(f"- From {q['from']}: {q['body']}")
    lines.append(
        "Answer in your speech by naming the asker. An unanswered question "
        "appears in the digest for the whole floor to see."
    )
    return "\n".join(lines)


def log_line(questions: list[dict]) -> str:
    if not questions:
        return "(none)"
    return "; ".join(f"{q['from']}→{q['to']}: {q['body'][:60]}" for q in questions)

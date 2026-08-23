"""Term record: platform promises vs. delivered work, graded at term end."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FILE = "terms.json"


def _path(root: Path) -> Path:
    return root / FILE


def load(root: Path) -> list[dict]:
    p = _path(root)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save(root: Path, terms: list[dict]) -> None:
    _path(root).write_text(json.dumps(terms, indent=2) + "\n", encoding="utf-8")


def open_term(root: Path, *, holder: str, turn: int, platform: str) -> None:
    """Record a new presidency and the platform it won on."""
    terms = [t for t in load(root) if not t.get("closed")]
    terms.append(
        {
            "holder": holder,
            "start_turn": int(turn),
            "platform": str(platform or "")[:400],
            "promises": [],
            "delivered": [],
            "closed": False,
        }
    )
    save(root, terms)


def add_promise(root: Path, *, holder: str, text: str) -> None:
    """Attach a promise made during the term (set_goal texts count)."""
    terms = load(root)
    for t in terms:
        if t.get("holder") == holder and not t.get("closed"):
            promises = list(t.get("promises") or [])
            if text[:200] not in promises:
                promises.append(text[:200])
            t["promises"] = promises[-6:]
            break
    save(root, terms)


def mark_delivered(root: Path, *, holder: str, rel_path: str) -> None:
    terms = load(root)
    for t in terms:
        if t.get("holder") == holder and not t.get("closed"):
            delivered = list(t.get("delivered") or [])
            if rel_path not in delivered:
                delivered.append(rel_path)
            t["delivered"] = delivered
            break
    save(root, terms)


def close_term(root: Path, *, turn: int) -> dict | None:
    """Close any open term. Returns the closed record with its score."""
    terms = load(root)
    closed_rec = None
    for t in terms:
        if t.get("closed"):
            continue
        promised = len(t.get("promises") or [])
        delivered = len(t.get("delivered") or [])
        t["closed"] = True
        t["end_turn"] = int(turn)
        t["score"] = f"{min(delivered, promised)}/{promised}" if promised else (
            f"{delivered} files"
        )
        closed_rec = t
    if closed_rec is not None:
        save(root, terms)
    return closed_rec


def latest_closed(root: Path, limit: int = 2) -> list[dict]:
    return [t for t in load(root) if t.get("closed")][-limit:]


def card(root: Path) -> str:
    """Track-record block for citizen cards."""
    closed = latest_closed(root)
    open_terms = [t for t in load(root) if not t.get("closed")]
    lines: list[str] = []
    if open_terms:
        t = open_terms[-1]
        promised = len(t.get("promises") or [])
        delivered = len(t.get("delivered") or [])
        lines.append(
            f"Current term ({t.get('holder')}): {delivered}/{promised} promises "
            "backed by delivered artifacts."
        )
    for t in closed:
        lines.append(
            f"Last term ({t.get('holder')}, turns {t.get('start_turn')}-{t.get('end_turn')}): "
            f"platform was \"{(t.get('platform') or '')[:120]}\" — scored {t.get('score')}."
        )
    if not lines:
        return ""
    out = ["TERM RECORD (promises vs. delivery; the floor grades this):"]
    out.extend(f"- {line}" for line in lines)
    return "\n".join(out)

"""Standing committees: divided labor with real, host-enforced jurisdiction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FILE = "committees.json"


def load(root: Path) -> dict[str, dict]:
    p = root / FILE
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save(root: Path, data: dict[str, dict]) -> None:
    (root / FILE).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def create(root: Path, *, name: str, members: list[str], chair: str | None = None) -> str | None:
    """Create or replace a committee. Returns an error string or None."""
    name = (name or "").strip().lower().replace(" ", "_")[:32]
    if not name:
        return "committee ignored (need a name)"
    roster = [m for m in members if m]
    if len(roster) < 1:
        return "committee ignored (need at least one member)"
    data = load(root)
    data[name] = {"members": roster[:5], "chair": chair if chair in roster else roster[0]}
    save(root, data)
    return None


def dissolve(root: Path, *, name: str) -> bool:
    data = load(root)
    name = (name or "").strip().lower().replace(" ", "_")[:32]
    if name not in data:
        return False
    del data[name]
    save(root, data)
    return True


def memberships_for(root: Path, member_id: str) -> list[dict]:
    out = []
    for name, c in load(root).items():
        if member_id in (c.get("members") or []):
            out.append(
                {
                    "name": name,
                    "chair": c.get("chair") == member_id,
                }
            )
    return out


def committee_card(root: Path) -> str:
    """Roster block for every citizen card."""
    data = load(root)
    if not data:
        return ""
    lines = ["Committees:"]
    for name, c in sorted(data.items()):
        chair = c.get("chair")
        roster = ", ".join(
            f"{m}{' (chair)' if m == chair else ''}" for m in c.get("members") or []
        )
        lines.append(f"- {name}: {roster}")
    lines.append(
        "Only a committee member may write_workspace under its path prefix "
        "(workspace/<name>/...); the chair may do so alone. Motion to form "
        "or change committees via appoint effects."
    )
    return "\n".join(lines)


def gate_write(root: Path, rel_path: str, member_id: str, president: str | None) -> str | None:
    """Enforce committee jurisdiction. Returns refusal note or None to allow.

    Rules: paths outside any committee prefix are unaffected. A path inside
    workspace/<committee>/ requires membership; the chair (or President)
    may always write there.
    """
    parts = Path(rel_path).parts
    if not parts:
        return None
    top = parts[0]
    data = load(root)
    if top not in data:
        return None
    c = data[top]
    if member_id == president:
        return None
    if member_id == c.get("chair"):
        return None
    if member_id in (c.get("members") or []):
        return None
    return (
        f"write_workspace refused ({top}/ is {name_or(top)}'s committee; only "
        f"{', '.join(c.get('members') or [])} may write there)"
    )


def name_or(slug: str) -> str:
    return slug.replace("_", " ")

"""Treasury: the nation's real budget. Arithmetic the chamber can trace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adags.constitution import value

FILE = "treasury.json"
HISTORY_CAP = 60


def path(root: Path) -> Path:
    return root / FILE


def load(root: Path) -> dict:
    p = path(root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save(root: Path, data: dict) -> None:
    path(root).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def init(root: Path, *, law: dict) -> dict:
    """Seed the ledger once. Existing runs without a treasury start funded."""
    data = load(root)
    if data.get("credits") is not None:
        return data
    data = {
        "credits": int(value(law, "economy.seed", 24)),
        "history": [],
    }
    save(root, data)
    return data


def enabled(law: dict) -> bool:
    return bool(value(law, "economy.enabled", True))


def credits(root: Path) -> int:
    data = load(root)
    try:
        return int(data.get("credits") or 0)
    except (TypeError, ValueError):
        return 0


def insolvent(root: Path) -> bool:
    return enabled({}) is not False and credits(root) < 0


def record(root: Path, turn: int, entries: list[tuple[int, str]]) -> None:
    data = load(root)
    hist = list(data.get("history") or [])
    for delta, why in entries:
        hist.append({"turn": int(turn), "delta": int(delta), "why": why})
    data["history"] = hist[-HISTORY_CAP:]
    save(root, data)


def settle(
    root: Path,
    *,
    law: dict,
    turn: int,
    n_members: int,
    goals: dict[str, str],
    goal_clock_text: str,
) -> list[str]:
    """Apply one turn of income and upkeep. Returns human-readable notes."""
    if not enabled(law):
        return []
    data = init(root, law=law)
    balance = int(data.get("credits") or 0)

    upkeep = int(value(law, "economy.member_upkeep", 1))
    drain = int(value(law, "economy.empty_register_drain", 2))
    yield_complete = int(value(law, "economy.goal_complete_yield", 8))
    dividend = int(value(law, "economy.complete_dividend", 1))

    entries: list[tuple[int, str]] = []
    # Income: each goal pays its yield exactly once, when first seen complete.
    paid = set(data.get("paid") or [])
    n_complete = 0
    for line in goal_clock_text.split("; "):
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "complete":
            gid = parts[0]
            n_complete += 1
            if gid not in paid and yield_complete:
                entries.append((yield_complete, f"goal {gid} complete"))
                paid.add(gid)
    # Dividend: completed goals keep paying a small per-turn income, so a
    # productive nation reaches sustainable solvency instead of doom-spiraling.
    if dividend and n_complete:
        entries.append((dividend * n_complete, f"dividend x{n_complete}"))
    # Upkeep: every seated member draws a salary.
    if upkeep and n_members:
        entries.append((-upkeep * n_members, f"upkeep x{n_members}"))
    # Drain: an empty register means nobody is producing anything.
    if drain and not goals:
        entries.append((-drain, "empty goal register"))

    if not entries:
        return []
    for delta, _why in entries:
        balance += delta
    data["credits"] = balance
    data["paid"] = sorted(paid)
    save(root, data)
    record(root, turn, entries)

    notes = [f"treasury {'+' if delta >= 0 else ''}{delta} ({why})" for delta, why in entries]
    if balance < 0:
        notes.append(
            f"treasury DEFICIT {balance}: seating new members is blocked until "
            "completed goals refill the coffers"
        )
    return notes


def card(root: Path, *, law: dict, n_members: int | None = None) -> str:
    """One-line treasury state for citizen cards."""
    if not enabled(law):
        return ""
    balance = credits(root)
    data = load(root)
    recent = list(data.get("history") or [])[-3:]
    flow = ", ".join(f"t{h['turn']} {h['delta']:+d} ({h['why']})" for h in recent)
    upkeep = int(value(law, "economy.member_upkeep", 1))
    lines = [f"Treasury: {balance} credits."]
    if flow:
        lines.append(f"Recent: {flow}.")
    if balance < 0:
        lines.append(
            "DEFICIT: the host will refuse add_member until completed goals "
            "(goal_complete_yield each) restore solvency."
        )
    if n_members is not None:
        lines.append(
            f"Marginal math: seating one more member costs {upkeep}/turn; "
            f"removing one saves {upkeep}/turn. Current payroll: {n_members} "
            f"= -{upkeep * n_members}/turn."
        )
    lines.append(
        "Every seated member costs upkeep each turn; a completed goal pays "
        "yield plus a per-turn dividend; an empty goal register drains. "
        "Finish work or shrink payroll."
    )
    return "\n".join(lines)


def gate_add_member(root: Path, *, law: dict) -> str | None:
    """Enforcement hook: refuse growth while insolvent."""
    if not enabled(law):
        return None
    balance = credits(root)
    if balance < 0:
        return (
            f"add_member refused (treasury {balance}: cannot pay a new salary; "
            "complete a goal first)"
        )
    return None

"""Mechanical interior law: votes, terms, privileges, elections."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from adags.seed import MEMBER_ID_RE

VALID_MEMBER_ID = re.compile(MEMBER_ID_RE)

THRESHOLD_NAMES = {
    "majority": lambda n: n // 2 + 1,
    "plurality": lambda n: 1,
    "unanimous": lambda n: n,
    "two_thirds": lambda n: (2 * n + 2) // 3,
}


def member_ids(members: list[dict]) -> list[str]:
    return [m["id"] for m in members]


def is_member_id(value: str) -> bool:
    return bool(VALID_MEMBER_ID.match(value or ""))


_MEMBER_IN_BLOB = re.compile(
    r"(?:member|id|vote|candidate|choice)['\"]?\s*[:=]\s*['\"]([a-z][a-z0-9_-]{0,31})['\"]",
    re.I,
)


def as_member_id(value: Any) -> str | None:
    """Accept a slug, or the objects models emit instead of a slug."""
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in {
            "aye",
            "nay",
            "abstain",
            "yes",
            "no",
            "none",
            "null",
            "true",
            "false",
        }:
            return None
        if is_member_id(text):
            return text
        found = _MEMBER_IN_BLOB.search(text)
        if found and is_member_id(found.group(1)):
            return found.group(1)
        return None
    if isinstance(value, dict):
        for key in ("member", "id", "vote", "vote_election", "candidate", "choice"):
            got = as_member_id(value.get(key))
            if got:
                return got
    return None


def as_party_id(value: Any) -> str | None:
    """Party slug, or none/leave to exit. Null/omit is 'no change' (caller)."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"", "none", "null", "leave", "independent"}:
            return ""
        if is_member_id(text):
            return text
        return None
    if isinstance(value, dict):
        for key in ("party", "id", "name", "join"):
            got = as_party_id(value.get(key))
            if got is not None:
                return got
    return None


def party_roster(members: list[dict]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {}
    for m in members:
        p = str(m.get("party") or "").strip()
        if p:
            buckets.setdefault(p, []).append(m["id"])
    return buckets


def apply_party(members: list[dict], member_id: str, party: str) -> list[dict]:
    """party '' means leave. Returns a new members list."""
    out = deepcopy(members)
    for m in out:
        if m["id"] == member_id:
            if party:
                m["party"] = party
            else:
                m.pop("party", None)
            break
    return out


def as_flag(value: Any) -> bool:
    """True only for real impeach/yes marks. The string 'false' is false."""
    if value is True or value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in {"true", "yes", "impeach"}:
        return True
    return False


def threshold(rule: str, n: int) -> int:
    if n <= 0:
        return 1
    fn = THRESHOLD_NAMES.get(rule, THRESHOLD_NAMES["majority"])
    return max(1, fn(n))


def passes(ayes: int, n: int, rule: str = "majority") -> bool:
    return ayes >= threshold(rule, n)


def office(gov: dict, name: str = "president") -> dict | None:
    return (gov.get("offices") or {}).get(name)


def president_id(gov: dict) -> str | None:
    off = office(gov)
    if not off:
        return None
    return off.get("holder")


def who_may(gov: dict, effect_type: str, members: list[dict]) -> set[str]:
    """If any office lists this effect as a privilege, only those holders may do it."""
    gated: set[str] = set()
    any_gate = False
    for off in (gov.get("offices") or {}).values():
        privs = off.get("privileges") or []
        if effect_type in privs:
            any_gate = True
            holder = off.get("holder")
            if holder:
                gated.add(holder)
    if not any_gate:
        return set(member_ids(members))
    return gated


def may_execute(gov: dict, actor: str, effect_type: str, members: list[dict]) -> bool:
    return actor in who_may(gov, effect_type, members)


def term_expired(gov: dict, turn: int) -> bool:
    off = office(gov)
    if not off or not off.get("holder"):
        return False
    start = off.get("term_start")
    length = int(gov.get("term_length") or 4)
    if start is None:
        return True
    return turn >= int(start) + length


def president_vacant(gov: dict) -> bool:
    off = office(gov)
    return off is None or not off.get("holder")


def election_due(gov: dict, turn: int) -> bool:
    if not gov.get("election_enabled", True):
        return False
    if office(gov) is None:
        return False
    return president_vacant(gov) or term_expired(gov, turn)


def advance_phase(gov: dict, turn: int) -> dict:
    """Return a new gov with election_phase updated at the start of a turn."""
    g = deepcopy(gov)
    if not g.get("election_enabled", True) or office(g) is None:
        g["election_phase"] = "idle"
        return g
    phase = g.get("election_phase") or "idle"
    due = election_due(g, turn)
    if not due:
        g["election_phase"] = "idle"
        return g
    if phase == "idle":
        g["election_phase"] = "nominate"
        g["ballots"] = {}
        if president_vacant(g):
            g["nominees"] = []
    elif phase == "nominate":
        if g.get("nominees"):
            g["election_phase"] = "ballot"
        else:
            g["election_phase"] = "nominate"
    elif phase == "ballot":
        # still ballot until resolve_ballot seats someone
        g["election_phase"] = "ballot"
    return g

def add_nominee(gov: dict, *, member: str, platform: str, nominator: str, turn: int) -> dict | str:
    g = deepcopy(gov)
    if g.get("election_phase") != "nominate":
        return "nominations are not open"
    if not is_member_id(member):
        return "invalid member id"
    existing = {n["member"] for n in g.get("nominees") or []}
    if member in existing:
        return "already nominated"
    g.setdefault("nominees", []).append(
        {
            "member": member,
            "platform": (platform or "").strip(),
            "nominator": nominator,
            "turn": turn,
        }
    )
    return g


def plurality_winner(votes: dict[str, str], nominees: list[dict]) -> str | None:
    """votes: voter -> candidate. Earliest nomination wins a tie. None if no valid votes."""
    order = [n["member"] for n in nominees]
    allowed = set(order)
    tallies: dict[str, int] = {c: 0 for c in order}
    for choice in votes.values():
        pick = as_member_id(choice)
        if pick in allowed:
            tallies[pick] += 1
    if not any(tallies.values()):
        return None
    best = max(tallies.values())
    tied = [c for c, n in tallies.items() if n == best]
    for name in order:
        if name in tied:
            return name
    return tied[0]


def seat_president(gov: dict, holder: str, turn: int) -> dict:
    g = deepcopy(gov)
    g.setdefault("offices", {}).setdefault("president", {})
    g["offices"]["president"]["holder"] = holder
    g["offices"]["president"]["term_start"] = turn
    g["election_phase"] = "idle"
    g["nominees"] = []
    g["ballots"] = {}
    return g


def vacate_president(gov: dict) -> dict:
    g = deepcopy(gov)
    if "president" in (g.get("offices") or {}):
        g["offices"]["president"]["holder"] = None
        g["offices"]["president"]["term_start"] = None
    g["election_phase"] = "nominate"
    g["nominees"] = []
    g["ballots"] = {}
    return g

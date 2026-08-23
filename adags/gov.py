"""Transient vote, term, and election state."""

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
    r"(?:member|id|vote|candidate|choice|nominee|nominated|target|pick|successor)['\"]?\s*[:=]\s*['\"]([a-z][a-z0-9_-]{0,31})['\"]",
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
            "a",
            "an",
            "any",
            "anyone",
            "someone",
            "phase",
            "idle",
            "ballot",
            "election",
            "nominate",
            "nominee",
            "member",
            "candidate",
            "president",
            "self",
        }:
            return None
        if is_member_id(text):
            return text
        found = _MEMBER_IN_BLOB.search(text)
        if found and is_member_id(found.group(1)):
            return found.group(1)
        return None
    if isinstance(value, dict):
        for key in (
            "member",
            "id",
            "vote",
            "vote_election",
            "candidate",
            "choice",
            "nominee",
            "nominated",
            "target",
            "pick",
            "successor",
            "for",
            "name",
        ):
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


def member_party(members: list[dict] | None, member_id: str) -> str:
    for member in members or []:
        if member.get("id") == member_id:
            return str(member.get("party") or "").strip()
    return ""


def party_tickets(gov: dict | None) -> dict[str, str]:
    raw = (gov or {}).get("party_tickets") or {}
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for name, holder in raw.items():
        party = str(name or "").strip()
        ticket = as_member_id(holder)
        if party and ticket:
            out[party] = ticket
    return out


def format_party_tickets(gov: dict | None) -> str:
    tickets = party_tickets(gov)
    if not tickets:
        return "(none)"
    return ", ".join(f"{party}={holder}" for party, holder in sorted(tickets.items()))


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
    marked, _ = as_impeach(value)
    return marked


def as_impeach(value: Any) -> tuple[bool, str | None]:
    """Impeach mark plus optional chamber/host article id."""
    if value is True or value == 1:
        return True, None
    if value is False or value is None or value == 0:
        return False, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(value)
        if n >= 200:
            return True, f"{n:03d}"
        return bool(n), None
    if isinstance(value, str):
        text = value.strip()
        low = text.lower()
        if low in {"false", "no", "none", "null", ""}:
            return False, None
        if low in {"true", "yes", "impeach"}:
            return True, None
        # Negligence charge: impeach without a cited article still counts when
        # the member names a concrete failure instead of a bare threat.
        if low in {"negligence", "dereliction"} or low.startswith("negligence"):
            return True, "negligence"
        found = re.search(r"(\d{3})", text)
        if found and int(found.group(1)) >= 200:
            return True, found.group(1)
        return False, None
    if isinstance(value, dict):
        for key in ("article", "id", "rule", "charge", "cite"):
            if value.get(key) is not None:
                marked, art = as_impeach(value.get(key))
                if marked:
                    return True, art
        if value.get("impeach") not in (None, value):
            return as_impeach(value.get("impeach"))
    return False, None


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




def term_expired(gov: dict, turn: int) -> bool:
    off = office(gov)
    if not off or not off.get("holder"):
        return False
    start = off.get("term_start")
    length = int(gov.get("term_length") or 8)
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


def advance_phase(gov: dict, turn: int, *, motion_open: bool = False) -> dict:
    """Return a new gov with election_phase updated at the start of a turn.

    An open motion keeps an idle chamber idle so the bill finishes before
    nominations. Nominate/ballot already in progress still run.
    """
    g = deepcopy(gov)
    if not g.get("election_enabled", True) or office(g) is None:
        g["election_phase"] = "idle"
        return g
    phase = g.get("election_phase") or "idle"
    due = election_due(g, turn)
    if not due:
        g["election_phase"] = "idle"
        return g
    if motion_open and phase == "idle":
        g["election_phase"] = "idle"
        return g
    if phase == "idle":
        g["election_phase"] = "nominate"
        g["ballots"] = {}
        g["party_tickets"] = {}
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

def consecutive_blocked(gov: dict) -> str | None:
    """Sitting President who may not succeed themselves, or None."""
    limit = gov.get("consecutive_limit", 1)
    if limit is None:
        return None
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return None
    if limit < 1:
        return None
    return president_id(gov)


def add_nominee(
    gov: dict,
    *,
    member: str,
    platform: str,
    nominator: str,
    turn: int,
    members: list[dict] | None = None,
    caucus_primary: bool = True,
) -> dict | str:
    g = deepcopy(gov)
    if g.get("election_phase") != "nominate":
        return "nominations are not open"
    if not is_member_id(member):
        return "invalid member id"
    blocked = consecutive_blocked(g)
    if blocked and member == blocked:
        return f"{member} is ineligible this election (consecutive term)"
    nom_party = member_party(members, nominator)
    tickets = party_tickets(g)
    remapped = False
    if caucus_primary and nom_party and tickets.get(nom_party) and member != tickets[nom_party]:
        member = tickets[nom_party]
        remapped = True
    if blocked and member == blocked:
        return f"{member} is ineligible this election (consecutive term)"
    existing = {n["member"] for n in g.get("nominees") or []}
    if member in existing:
        if nom_party and tickets.get(nom_party) == member:
            return f"seconded {member} ({nom_party} ticket)"
        return "already nominated"
    target_party = member_party(members, member)
    if caucus_primary and nom_party and target_party == nom_party and nom_party not in tickets:
        tickets[nom_party] = member
    g["party_tickets"] = tickets
    g.setdefault("nominees", []).append(
        {
            "member": member,
            "platform": (platform or "").strip(),
            "nominator": nominator,
            "turn": turn,
        }
    )
    return g


def election_tally(votes: dict[str, str], nominees: list[dict]) -> dict[str, int]:
    order = [n["member"] for n in nominees]
    allowed = set(order)
    tallies: dict[str, int] = {c: 0 for c in order}
    for choice in votes.values():
        pick = as_member_id(choice)
        if pick in allowed:
            tallies[pick] += 1
    return tallies


def format_tally(tallies: dict[str, int]) -> str:
    bits = [f"{name} {count}" for name, count in tallies.items() if count]
    return ", ".join(bits) or "none"


def tied_leaders(tallies: dict[str, int]) -> list[str]:
    if not any(tallies.values()):
        return []
    best = max(tallies.values())
    return [name for name, count in tallies.items() if count == best]


def seat_summary(votes: dict[str, str], nominees: list[dict], winner: str) -> str:
    tallies = election_tally(votes, nominees)
    scored = format_tally(tallies)
    tied = tied_leaders(tallies)
    if len(tied) > 1:
        return f"seated {winner} ({scored}; tie → earliest nominee)"
    return f"seated {winner} ({scored})"


def apply_caucus_ballot(
    voter: str,
    pick: str,
    members: list[dict] | None,
    gov: dict | None,
    *,
    caucus_primary: bool = True,
) -> tuple[str, str | None]:
    """Self-votes from a caucus member become a vote for that ticket."""
    if not caucus_primary:
        return pick, None
    party = member_party(members, voter)
    ticket = party_tickets(gov).get(party)
    if ticket and pick == voter and pick != ticket:
        return ticket, f"ballot remapped to {ticket} ({party} ticket)"
    return pick, None


def plurality_winner(votes: dict[str, str], nominees: list[dict]) -> str | None:
    """votes: voter -> candidate. Earliest nomination wins a tie. None if no valid votes."""
    tallies = election_tally(votes, nominees)
    if not any(tallies.values()):
        return None
    tied = tied_leaders(tallies)
    for nominee in nominees:
        name = nominee["member"]
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
    g["party_tickets"] = {}
    g["policy_due"] = True
    return g


def vacate_president(gov: dict) -> dict:
    g = deepcopy(gov)
    if "president" in (g.get("offices") or {}):
        g["offices"]["president"]["holder"] = None
        g["offices"]["president"]["term_start"] = None
    g["election_phase"] = "nominate"
    g["nominees"] = []
    g["ballots"] = {}
    g["party_tickets"] = {}
    return g

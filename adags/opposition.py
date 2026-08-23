"""The loyal opposition: the largest non-presidential caucus is recognized."""

from __future__ import annotations

from adags.gov import party_roster, president_id


def opposition_id(members: list[dict], gov: dict, law: dict | None = None) -> str | None:
    """Return the member id recognized as Leader of the Opposition, or None.

    The largest caucus whose members do not include the sitting President
    supplies the leader (its first seated member by roster order). Ties go
    to the alphabetically first party.
    """
    prez = president_id(gov)
    roster = party_roster(members)
    best = None  # (size, party)
    for party, ids in sorted(roster.items()):
        if prez in ids:
            continue
        if best is None or len(ids) > best[0]:
            best = (len(ids), party)
    if not best or best[0] < 2:
        return None  # a lone member is a critic, not an opposition
    party = best[1]
    ids = [m["id"] for m in members if m.get("party") == party]
    return ids[0] if ids else None


def opposition_card(
    members: list[dict], gov: dict, *, member_id: str, motions_opened: int = 0
) -> str:
    """Per-citizen note explaining opposition standing and its privilege."""
    leader = opposition_id(members, gov)
    if not leader:
        return ""
    from adags.gov import party_roster

    prez = president_id(gov) or "(vacant)"
    roster = party_roster(members)
    opp_party = next(
        (p for p, ids in roster.items() if leader in ids), "(unknown)"
    )
    if member_id == leader:
        return (
            f"You are recognized as Leader of the Opposition ({opp_party}, vs. "
            f"President {prez}). Privilege: your first motion each term skips "
            f"the proposer gate. Used this term: {motions_opened}. Duty: hold "
            "the government to account — question, audit, and offer the alternative."
        )
    if member_id == prez:
        return (
            f"The opposition ({opp_party}) is recognized under {leader}. "
            "Expect their questions and answer them on the record."
        )
    return f"Leader of the Opposition: {leader} ({opp_party})."

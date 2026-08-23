"""Per-citizen sentiment ledger, built only from observed public and private acts."""

from __future__ import annotations

from typing import Any

CLAMP = 5.0

# How strongly each observed signal moves feeling.
WHISPER_BOND = 1.5
NOMINATE_BOND = 1.0
CROSS_PARTY_ENDORSEMENT = 1.5
SAME_PARTY_ENDORSEMENT = 0.5
SPEECH_MENTION = 0.25
IMPEACH_SLIGHT = 2.0


def _clamp(value: float) -> float:
    return max(-CLAMP, min(CLAMP, round(float(value), 2)))


def note(relations: dict, actor: str, other: str, delta: float) -> None:
    """Record that `actor` warmed (or cooled) toward `other`."""
    if not actor or not other or actor == other:
        return
    row = relations.setdefault(actor, {})
    row[other] = _clamp(row.get(other, 0.0) + delta)
    if row[other] == 0.0:
        del row[other]


def update_from_act(
    relations: dict,
    *,
    actor: str,
    act: dict[str, Any],
    seated: list[str],
    president: str | None,
    member_party_of,
) -> None:
    """Fold one citizen's validated act into the ledger. Mutates `relations`.

    `member_party_of(member_id) -> str | ""` resolves caucus membership so a
    cross-ticket endorsement reads as bridge-building rather than loyalty.
    """
    seated_set = set(seated)

    whisper = act.get("whisper")
    if isinstance(whisper, dict):
        target = str(whisper.get("to") or "")
        if target in seated_set:
            note(relations, actor, target, WHISPER_BOND)

    nom = act.get("nominate")
    if isinstance(nom, dict):
        from adags.gov import as_member_id

        target = as_member_id(nom.get("member")) or as_member_id(nom)
        if target in seated_set and target != actor:
            note(relations, actor, target, NOMINATE_BOND)

    from adags.gov import as_member_id

    ballot = as_member_id(act.get("vote_election"))
    if ballot in seated_set and ballot != actor:
        mine = member_party_of(actor)
        theirs = member_party_of(ballot)
        delta = (
            CROSS_PARTY_ENDORSEMENT
            if mine != theirs
            else SAME_PARTY_ENDORSEMENT
        )
        note(relations, actor, ballot, delta)

    from adags.gov import as_impeach

    marked, _article = as_impeach(act.get("impeach"))
    if marked and president and president in seated_set:
        note(relations, actor, president, -IMPEACH_SLIGHT)

    speech = str(act.get("speech") or "").lower()
    if speech:
        for other in seated_set:
            if other != actor and other in speech:
                note(relations, actor, other, SPEECH_MENTION)


def format_standing(
    relations: dict, member_id: str, seated: list[str], *, limit: int = 4
) -> str:
    """How the chamber leans toward this citizen, and vice versa."""
    seated_set = set(seated)
    toward: list[tuple[float, str]] = []
    own: list[tuple[float, str]] = []
    for actor, row in relations.items():
        if actor == member_id or actor not in seated_set:
            continue
        value = float((row or {}).get(member_id, 0.0))
        if abs(value) >= 0.75:
            toward.append((value, actor))
    for other, value in sorted(
        (relations.get(member_id) or {}).items(),
        key=lambda kv: -abs(float(kv[1])),
    ):
        value = float(value)
        if other in seated_set and abs(value) >= 0.75:
            own.append((value, other))
    toward.sort(key=lambda pair: pair[0])
    own.sort(key=lambda pair: pair[0])

    def phrase(entries: list[tuple[float, str]]) -> list[str]:
        out = []
        for value, name in entries[:limit]:
            lean = "warm" if value > 0 else "cool"
            out.append(f"{name} ({lean} {value:+g})")
        return out

    lines = []
    if toward:
        lines.append("Colleagues lean toward you: " + ", ".join(phrase(toward)) + ".")
    if own:
        lines.append("You currently lean: " + ", ".join(phrase(own)) + ".")
    if not lines:
        return ""
    out = ["Standing among colleagues (observed from acts; whispers bond deepest,",
            "impeachment cuts hardest). Debts get called in; grudges vote:",
            *lines]
    # Saturation warning: near-unanimous warmth is a consensus trap.
    warm = [v for v, _ in toward if v > 0]
    if len(toward) >= 3 and len(warm) == len(toward):
        out.append(
            "WARNING: the whole chamber leans your way. Unanimity is not "
            "safety — it is a consensus trap. Court disagreement or you will "
            "drift unchallenged while real problems go unspoken."
        )
    return "\n".join(out)

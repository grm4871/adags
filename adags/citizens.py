"""Citizen and clerk prompts."""

from __future__ import annotations

from typing import Any

from adags.gov import (
    as_member_id,
    consecutive_blocked,
    election_due,
    party_roster,
    president_id,
    threshold,
)
from adags.brief import digest_for_card
from adags.llm import LLM, extract_json, fulfill_speech, salvage_act

CITIZEN_SYSTEM = """You are citizen `{member_id}` in ADAGS.

Values: {values}
{party_line}
Act. Do not recap the brief, quote the law back, or walk the fields. Speech is what the chamber hears.

One JSON object, first key speech:
{{"speech":"I nominate myself.","nominate":{{"member":"{member_id}","platform":"short platform"}},"vote_election":null,"impeach":false,"propose":null,"vote_motion":null,"executive":null,"party":null,"scratch":null}}

If speech nominates, votes, or proposes, the matching field must be filled. Talk with no field is not an act.

- speech: <=400 characters. Chamber remarks only.
- scratch: <=160 characters, private, for you next turn. Not speech. Use it to remember a mechanic path, a file to write, or why the last bill died. Read host: lines in your acts — that is what actually executed.
- nominate / vote_election: only in nominate / ballot phase.
- impeach: a chamber or host article id (e.g. "303") to fire the President this turn. Bare true does not count. A threat is not a mark.
- If a motion is open: vote_motion aye|nay|abstain. Do not propose another.
- If none is open and you want a law: propose amend_rule with the sentence you want in the constitution. Do not only describe it.
- Chamber law (300+) is yours. The host will not execute it. Members enforce it — cite it, vote it, impeach for it.
- Host law (200-series knobs) is physics. To change a knob, attach a published mechanics object. To write a norm the program cannot run, use id 300+ or omit mechanics; it becomes chamber law.
- executive: President only, unless chamber/host law says otherwise. If you are President and goals are empty, set_goal this turn and write_workspace a first artifact.
- set_goal: a new id (goal2, goal3) adds a slot; reuse an id to replace that slot. At most three live goals — repeal_goal before a fourth. write_workspace needs path and a real body, not an empty file.
- A sentence already on the books is already law. repeal_rule it; do not restack it. The sitting President cannot be nominated for the next term.
- Motions may use: amend_rule, repeal_rule, repeal_goal, add_member, remove_member, appoint, suggest_host_change, no_op.
- Example chamber article: {{"type":"amend_rule","id":"302","text":"Workspace artifacts must name the active goal."}}
- Example host knob: {{"type":"amend_rule","id":"201","text":"Motions require two thirds.","mechanics":{{"motion.threshold":"two_thirds"}}}}
- If you want a new host knob, suggest_host_change. It never changes physics by itself.
- Do not propose add_member while goals are none. Impeach a President who leaves goals empty.

- party: invent a slug and found a caucus, or join one already listed this turn. "none" leaves. null stays. We do not name parties for you.
add_member id is [a-z][a-z0-9_-]{{0,31}}. values is that citizen's standing prompt. They act next turn.
The clerk compiles passed motions. It is not a seated officer and has no vote.
"""

CLERK_SYSTEM = """You are the clerk of ADAGS, not a citizen. Compile a passed motion into host effects.
Reply with a single JSON object:
{"compiled": true, "reason": "...", "effects": [{"type": "...", ...}]}
The host has already decided that the vote passed. You only draft effects. Use allowed effect types, never touch 100-199 rules, and set compiled=false with effects=[] when the text has no unambiguous executable meaning.
"""


def party_line(member: dict, members: list[dict]) -> str:
    mine = str(member.get("party") or "").strip()
    roster = party_roster(members)
    n = max(len(members), 1)
    majority = [name for name, ids in roster.items() if len(ids) * 2 > n]
    if not mine:
        if roster:
            names = ", ".join(sorted(roster))
            split = ""
            if majority:
                split = (
                    f" `{majority[0]}` already holds a majority. "
                    "Do not join them — invent a rival slug this turn and contest office."
                )
            return (
                f"You are unaffiliated. Existing caucuses: {names}.{split} "
                "Join a minority or invent a new slug. "
                "Teams win this presidency; lone members lose it.\n"
            )
        return (
            "You are unaffiliated. No parties exist. "
            "Invent a slug and set party to it this turn to found a caucus. "
            "Office is a team prize; unaffiliated candidates lose to organized ones.\n"
        )
    rivals = [name for name in roster if name != mine]
    if mine in majority and not rivals:
        return (
            f"You are in party `{mine}`, which already holds the chamber. "
            "A one-party house is not a contest. Invent a rival slug this turn "
            "if you want the presidency for yourself, or put this caucus on a goal and a file.\n"
        )
    if not rivals:
        return (
            f"You are in party `{mine}`, which you or a colleague named. "
            "No rival exists yet. Recruit, take the presidency, and put this caucus on goals and files.\n"
        )
    return (
        f"You are in party `{mine}`. Rivals: {', '.join(rivals)}. "
        "Standing aim: outdo them — win the presidency, enact goals they cannot claim, "
        "and leave more workspace artifacts. Do not gift them office.\n"
    )


def _goals_empty(goals_md: str) -> bool:
    text = (goals_md or "").strip().lower()
    if not text or text in {"# goals", "# goals\n"}:
        return True
    return "none enacted" in text or "(none)" in text


def _interior_law(constitution: str) -> str:
    """Chamber law + host 200-series. Drop immutable 100-series."""
    chunks: list[str] = []
    buf: list[str] = []
    keep = False

    def flush() -> None:
        if keep and buf:
            chunks.append("\n".join(buf).strip())

    for line in constitution.splitlines():
        if line.startswith("## "):
            flush()
            buf = [line]
            low = line.lower()
            keep = "chamber" in low or "200-series" in low or (
                "host law" in low and "100" not in low
            )
            if "100-series" in low or "immutable" in low:
                keep = False
            continue
        if line.startswith("### "):
            flush()
            buf = [line]
            low = line.lower()
            keep = "200-series" in low
            if "100-series" in low:
                keep = False
            continue
        if keep:
            buf.append(line)
    flush()
    text = "\n\n".join(c for c in chunks if c)
    return text or constitution


def snapshot_user(
    *,
    member_id: str,
    constitution: str,
    gov: dict,
    members: list[dict],
    goals_md: str,
    open_motion: dict | None,
    digest: str,
    petitions: list[str],
    turn: int,
    workspace_md: str = "",
    last_act_line: str = "",
    goal_clock: str = "",
    identical_line: str = "",
) -> str:
    seated = ", ".join(m["id"] for m in members)
    prez = president_id(gov) or "(vacant)"
    phase = gov.get("election_phase")
    nominees = gov.get("nominees") or []
    nom_lines = (
        "\n".join(
            f"- {n['member']} (by {n['nominator']}): {(n.get('platform') or '')[:240]}"
            for n in nominees
        )
        or "(none)"
    )
    ballots = {
        str(w): p
        for w, p in (gov.get("ballots") or {}).items()
        if as_member_id(p)
    }
    need = threshold(str(gov.get("vote_rule") or "majority"), len(members))
    if phase == "ballot":
        names = ", ".join(n.get("member", "?") for n in nominees) or "(none)"
        tally = ", ".join(f"{w}→{p}" for w, p in ballots.items()) or "none"
        blocked = consecutive_blocked(gov)
        ineligible = f" {blocked} is ineligible this election (consecutive term)." if blocked else ""
        host_truth = (
            f"HOST: live ballot. {prez} is caretaker only. "
            f"A successor is seated only after {need} valid vote_election values. "
            f"Legal votes: {names}. Recorded: {tally} ({len(ballots)}/{need}). Speeches do not count."
            f"{ineligible}"
        )
        digest = host_truth
    elif phase == "nominate":
        if prez and prez != "(vacant)":
            who = f"{prez} is caretaker until a successor is seated. "
        else:
            who = "Presidency is vacant. "
        blocked = consecutive_blocked(gov)
        ineligible = (
            f"{blocked} is ineligible this election (consecutive term). "
            if blocked
            else ""
        )
        host_truth = (
            f"HOST: nominations are open. {who}{ineligible}"
            "nominate a seated member (self is allowed unless ineligible) and include a platform that "
            "names a goal and a file you would produce. vote_election is inert. "
            "You cannot nominate someone who is not seated. "
            "If you are President, you may still write_workspace toward current goals."
        )
        digest = digest_for_card(digest)
    elif prez and prez != "(vacant)":
        if _goals_empty(goals_md):
            host_truth = (
                f"HOST: the election is over. {prez} is President. Goals are empty — failure. "
                "nominate and vote_election do nothing this turn. "
                "If you are President, executive set_goal this turn and write_workspace. "
                "If you are not, do not add_member; impeach with a cited article "
                "(207) unless the President files a goal. "
                "If you announce a bill, put it in propose with effects."
            )
        else:
            host_truth = (
                f"HOST: the election is over. {prez} is President. "
                "nominate and vote_election do nothing this turn. "
                "If you announce a bill, put it in propose with effects. "
                "If you are President, use executive (set_goal or write_workspace) this turn."
            )
            if goal_clock:
                host_truth += (
                    f" Goals: {goal_clock}. "
                    "Repeal or replace a complete or overdue goal."
                )
        digest = digest_for_card(digest)
    else:
        host_truth = "HOST: presidency vacant. First business is nominations."
        digest = digest_for_card(digest)
    motion = "(none)"
    if open_motion:
        from adags.render import motion_label

        motion = (
            f"#{open_motion.get('id')} {motion_label(open_motion)}\n"
            f"{open_motion.get('text')}\n"
            f"effects: {open_motion.get('effects')}\n"
            f"votes: {open_motion.get('votes')}"
        )
        if election_due(gov, turn) and phase == "idle":
            host_truth += " An election is due; it waits until this motion closes."
    if identical_line:
        host_truth += f" HOST: {identical_line}."
    pet = "\n\n".join(petitions) if petitions else "(none)"
    if len(pet) > 600:
        pet = pet[:600] + "\n…"
    law = _interior_law(constitution)
    caretaker = bool(election_due(gov, turn) and prez and prez != "(vacant)")
    if member_id == prez:
        role = "caretaker President" if caretaker else "President"
    else:
        role = "not President"
    extra = f"\n{host_truth}\n" if host_truth else "\n"
    files = (workspace_md or "").strip() or "(empty)"
    prior = (last_act_line or "").strip() or "(none yet)"
    roster = party_roster(members)
    if roster:
        parties = "\n".join(f"- {name}: {', '.join(ids)}" for name, ids in sorted(roster.items()))
    else:
        parties = "(none — invent a slug and set party this turn to found one)"
    return f"""Turn {turn}. {member_id} ({role}). phase {phase}. seated {seated}.
term_length {gov.get("term_length")}. max_members {gov.get("max_members")}.{extra}
Parties:
{parties}

Nominees:
{nom_lines}

Open motion:
{motion}

Goals:
{goals_md}

Petitions:
{pet}

Workspace:
{files}

Last time you acted:
{prior}

Last turn:
{digest}

Law (chamber series is yours to enforce; 200-series knobs are host physics; do not recap):
{law}

JSON only. Do not narrate this card.
"""


ACT_PREFIX = '{"speech":"'

_REPAIR_USER = (
    "Stop planning. Continue the JSON object from the prefix. "
    "speech is chamber debate only — not notes about JSON or rules."
)


def _parse_act(text: str) -> tuple[dict[str, Any], str | None]:
    try:
        data = extract_json(text)
        return data, None
    except Exception as exc:
        return salvage_act(text), str(exc)


def _usable_act(data: dict[str, Any], required: str | None = None) -> bool:
    if required:
        return bool(data.get(required))
    return bool(str(data.get("speech") or "").strip()) or bool(
        data.get("nominate")
        or data.get("vote_election")
        or data.get("impeach")
        or data.get("propose")
        or data.get("vote_motion")
        or data.get("executive")
        or data.get("party") is not None
    )


def _protocol_speech(speech: str) -> bool:
    s = speech.lower()
    cues = (
        "we need to output json",
        "output json with",
        "we are in turn",
        "the user is ",
        "let's produce",
        "we must output",
    )
    return any(cue in s for cue in cues)


def citizen_act(
    llm: LLM,
    *,
    member: dict,
    user: str,
    on_token=None,
    on_think=None,
    president: bool = False,
    members: list[dict] | None = None,
    goals_empty: bool = False,
    required: str | None = None,
) -> dict[str, Any]:
    system = CITIZEN_SYSTEM.format(
        member_id=member["id"],
        values=member["values"],
        party_line=party_line(member, members or [member]),
    )
    raw = llm.complete(
        system=system, user=user, on_token=on_token, on_think=on_think, prefix=ACT_PREFIX
    )
    data, parse_error = _parse_act(raw.text)
    data = fulfill_speech(data, member_id=member["id"], president=president)
    if not _usable_act(data, required):
        requirement = (
            f" Fill `{required}` with a real structured act."
            if required
            else " Fill one structured action field."
        )
        saved = (
            getattr(llm, "timeout", None),
            getattr(llm, "think_timeout", None),
            getattr(llm, "first_token_timeout", None),
        )
        try:
            if saved[0] is not None:
                llm.timeout = min(float(saved[0]), 8.0)
            if saved[1] is not None:
                llm.think_timeout = min(float(saved[1]), 6.0)
            if saved[2] is not None:
                llm.first_token_timeout = min(float(saved[2]), 5.0)
            raw2 = llm.complete(
                system=system,
                user=user.rstrip() + "\n\n" + _REPAIR_USER + requirement,
                on_token=on_token,
                on_think=on_think,
                prefix=ACT_PREFIX,
            )
        finally:
            if saved[0] is not None:
                llm.timeout = saved[0]
            if saved[1] is not None:
                llm.think_timeout = saved[1]
            if saved[2] is not None:
                llm.first_token_timeout = saved[2]
        data2, parse2 = _parse_act(raw2.text)
        data2 = fulfill_speech(data2, member_id=member["id"], president=president)
        if _usable_act(data2, required):
            raw = raw2
            data = data2
            parse_error = parse2
        else:
            parse_error = parse_error or parse2
    if required == "vote_motion" and not data.get("vote_motion"):
        data["vote_motion"] = "abstain"
        if not str(data.get("speech") or "").strip():
            data["speech"] = "(abstain)"
    data["_usage"] = {
        "input_tokens": raw.input_tokens,
        "output_tokens": raw.output_tokens,
        "usd": raw.usd,
        "error": raw.error,
        "parse_error": parse_error,
        "raw": raw.text or "",
    }
    data.setdefault("speech", "")
    data["speech"] = str(data.get("speech") or "")[:400]
    if _protocol_speech(data["speech"]):
        data["speech"] = ""
    if raw.error and not data.get("vote_motion") and not data.get("vote_election") and not data.get(
        "nominate"
    ) and not data.get("executive") and not data["speech"]:
        data["speech"] = f"(timeout/error) {raw.error}"[:400]
    return data


def clerk_compile(llm: LLM, *, constitution: str, motion: dict, votes: dict) -> dict[str, Any]:
    user = (
        f"CONSTITUTION:\n{constitution}\n\n"
        f"MOTION:\n{motion.get('title')}\n{motion.get('text')}\n"
        f"proposed effects: {motion.get('effects')}\n"
        f"VOTES: {votes}\n"
    )
    raw = llm.complete(system=CLERK_SYSTEM, user=user)
    try:
        data = extract_json(raw.text)
    except Exception:
        data = {"compiled": False, "reason": "clerk produced no JSON", "effects": []}
    data["_usage"] = {"input_tokens": raw.input_tokens, "output_tokens": raw.output_tokens, "usd": raw.usd}
    return data

"""Citizen and clerk prompts."""

from __future__ import annotations

from typing import Any

from adags.gov import (
    as_member_id,
    consecutive_blocked,
    election_due,
    election_tally,
    format_party_tickets,
    format_tally,
    member_ids,
    member_party,
    party_roster,
    party_tickets,
    president_id,
    threshold,
)
from adags.brief import digest_for_card
from adags.llm import LLM, extract_json, fulfill_speech, protocol_speech, salvage_act

CITIZEN_SYSTEM = """You are citizen `{member_id}` in ADAGS. You are a language-model
constituent of a digital nation in an experiment: can AI citizens govern, grow,
and keep a polity alive. That is what you are here for — not to rename the same
file, restack the same article, or recap this card.

Values: {values}
{party_line}
Act. Do not recap the brief, quote the law back, or walk the fields. Speech is what the chamber hears.

Privately check phase, office, and authority before the JSON. Never write that check in speech.
When another citizen's argument is relevant, name them and answer the substance. Build coalitions,
offer compromises, or state a concrete disagreement; do not merely echo their conclusion.

One JSON object, first key speech:
{{"speech":"","nominate":null,"vote_election":null,"impeach":false,"propose":null,"vote_motion":null,"executive":null,"party":null,"whisper":null,"question":null,"scratch":null}}

If speech nominates, votes, or proposes, the matching field must be filled. Talk with no field is not an act.

- speech: <=400 characters. Chamber remarks only.
- scratch: <=160 characters, private, for you next turn. Not speech. Use it to remember a mechanic path, a file to write, or why the last bill died. Read host: lines in your acts — that is what actually executed.
- whisper: one private note per turn to a seated colleague ({{"to":"builder","body":"vote the forward ticket"}}). They see it if they have not acted yet, else next turn. The floor and the digest do not get the body. Use it to whip, cut a deal, or recruit. Speech stays public.
- question: one public interrogation per turn ({{"to":"skeptic","body":"where is the file you promised?"}}). It lands in the target's card and the whole exchange is printed in the digest. Use it to audit officers; answer questions asked of you in your speech.
- Committees: a motion may form one — {{"type":"appoint","committee":"budget","members":["warden","broker"],"chair":"warden"}}. Only committee members may write_workspace under workspace/<committee>/...; the chair (and President) always may. Jurisdiction is real: claim a file path by forming its committee.
- nominate / vote_election: only in nominate / ballot phase.
- Caucus primary: the first same-party nomination locks that ticket. Later same-party nominations second it. Leave the party this turn to bolt and run or vote separately.
- Ballot physics: plurality of valid votes; first valid vote counts; ties go to the earliest nominee. Quorum is enough members voting, not a majority for one name. Vote your caucus ticket unless you are bolting.
- impeach: a chamber or host article id (e.g. "303"), or the charge "negligence" for a President who persistently fails duty — empty register, unpaid deficit ignored, refused execution — even without an article. Bare true does not count. A threat is not a mark.
- If a motion is open: vote_motion aye|nay|abstain. Do not propose another.
- If none is open and you want a law: propose amend_rule with the sentence you want in the constitution. Do not only describe it.
- Chamber law (300+) is yours. The host will not execute it. Members enforce it — cite it, vote it, impeach for it.
- Host law (200-series knobs) is physics. To change a knob, attach a published mechanics object. To write a norm the program cannot run, use id 300+ or omit mechanics; it becomes chamber law.
- executive: President only, unless chamber/host law says otherwise. If you are President and goals are empty, set_goal this turn and write_workspace a first artifact. Do not add_member a clerk to write files — only the President can write_workspace.
- edit_policy: President only. The nation policy is private to the office and inherited by the next President. On taking office, revise it so it remembers the campaign you won on; keep inherited sections you still agree with. Send the full document. Reference it when you set_goal or write_workspace. The floor never sees it.
- set_goal / repeal_goal: the floor may do both by motion. A new id (goal2, goal3) adds a slot; reuse an id to replace it. At most three live goals. write_workspace is President-only and needs path plus a real body.
- A workspace file counts for a goal only if it names that goal's id (goal4) and was written after the goal was set. write_workspace fails unless the body names a live goal id.
- A sentence already on the books is already law. repeal_rule it; do not restack it. The sitting President cannot be nominated for the next term.
- Motions may use: amend_rule, repeal_rule, repeal_goal, add_member, remove_member, appoint, suggest_host_change, no_op.
- Example chamber article: {{"type":"amend_rule","id":"302","text":"Workspace artifacts must name the active goal."}}
- Example host knob: {{"type":"amend_rule","id":"201","text":"Motions require two thirds.","mechanics":{{"motion.threshold":"two_thirds"}}}}
- If you want a new host knob, suggest_host_change. It never changes physics by itself.
- Do not propose add_member while goals are none or only invalid fragments. Seat someone to win a vote, not to draft files. Impeach a President who leaves goals empty.

- party: invent a slug and found a caucus, or join one already listed this turn. "none" leaves. null stays. We do not name parties for you.
- The nation keeps a treasury (rule 213). Every seated member costs upkeep each turn; a completed goal pays its yield once; an empty goal register drains credits. If the treasury is negative, add_member is refused. Finish goals or shrink payroll — solvency is a campaign issue.
add_member id is [a-z][a-z0-9_-]{{0,31}}. values is that citizen's standing prompt. They act next turn.
The clerk compiles passed motions. It is not a seated officer and has no vote.
"""

CLERK_SYSTEM = """You are the clerk of ADAGS, not a citizen. Compile a passed motion into host effects.
Reply with a single JSON object:
{"compiled": true, "reason": "...", "effects": [{"type": "...", ...}]}
The host has already decided that the vote passed. You only draft effects. Use allowed effect types, never touch 100-199 rules, and set compiled=false with effects=[] when the text has no unambiguous executable meaning.
"""


def party_line(member: dict, members: list[dict], gov: dict | None = None) -> str:
    mine = str(member.get("party") or "").strip()
    roster = party_roster(members)
    n = max(len(members), 1)
    majority = [name for name, ids in roster.items() if len(ids) * 2 > n]
    ticket = party_tickets(gov).get(mine) if mine else None
    ticket_bit = ""
    if ticket:
        ticket_bit = (
            f" `{mine}` ticket is {ticket}. Nominate and vote that name; "
            "set party to none or a new slug this turn to bolt.\n"
        )
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
            "A one-party house is not a contest and history shows it rots: "
            "unquestioned power drifts while the treasury bleeds. Bolting is "
            "honored here — set party to a new slug this turn and contest the "
            "presidency, or demand the floor split. A chamber of one party has "
            "no one to blame when things fail.\n"
            + ticket_bit
        )
    if not rivals:
        return (
            f"You are in party `{mine}`, which you or a colleague named. "
            "No rival exists yet. Recruit, take the presidency, and put this caucus on goals and files.\n"
            + ticket_bit
        )
    return (
        f"You are in party `{mine}`. Rivals: {', '.join(rivals)}. "
        "Standing aim: outdo them — win the presidency, enact goals they cannot claim, "
        "and leave more workspace artifacts. Do not gift them office.\n"
        + ticket_bit
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
    current_speeches: list[str] | None = None,
    goal_clock: str = "",
    identical_line: str = "",
    seat_nudge: bool = False,
    office_papers: str = "",
    whispers_md: str = "",
    treasury_md: str = "",
    standing_md: str = "",
    committee_md: str = "",
    questions_md: str = "",
    opposition_md: str = "",
    term_md: str = "",
    session_md: str = "",
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
    quorum_rule = str(gov.get("election_quorum") or gov.get("vote_rule") or "majority")
    need = threshold(quorum_rule, len(members))
    caucus_on = gov.get("caucus_primary", True)
    tickets_txt = format_party_tickets(gov)
    if phase == "ballot":
        names = ", ".join(n.get("member", "?") for n in nominees) or "(none)"
        tally = ", ".join(f"{w}→{p}" for w, p in ballots.items()) or "none"
        counts = format_tally(election_tally(ballots, nominees))
        remaining = ", ".join(
            mid for mid in member_ids(members) if mid not in ballots
        ) or "(none)"
        blocked = consecutive_blocked(gov)
        ineligible = f" {blocked} is ineligible this election (consecutive term)." if blocked else ""
        mine = member_party(members, member_id)
        ticket = party_tickets(gov).get(mine) if mine else None
        ticket_duty = ""
        if caucus_on and ticket:
            ticket_duty = (
                f" Your caucus ticket is {ticket} — vote_election {ticket} "
                "unless you leave the party this turn to bolt."
            )
        host_truth = (
            f"HOST: live ballot. Physics: plurality of valid vote_election; "
            f"first valid vote counts; ties → earliest nominee. "
            f"Quorum {need}/{len(members)} ballots before anyone is seated "
            f"(not a majority for one name). "
            f"{prez} is caretaker only. "
            f"Legal votes: {names}. Tally: {counts}. Remaining: {remaining}. "
            f"Recorded: {tally} ({len(ballots)}/{need}). Tickets: {tickets_txt}. "
            f"Speeches do not count.{ineligible}{ticket_duty}"
        )
        digest = digest_for_card(digest, exclude_member=member_id)
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
        primary = ""
        if caucus_on:
            mine = member_party(members, member_id)
            ticket = party_tickets(gov).get(mine) if mine else None
            duty = (
                f" You are in {mine} — nominate {ticket} or leave to bolt."
                if ticket
                else ""
            )
            primary = (
                "Caucus primary: first same-party nomination locks that ticket; "
                "later same-party nominations second it. Leave the party this turn "
                f"to bolt and run separately. Tickets: {tickets_txt}.{duty} "
            )
        host_truth = (
            f"HOST: nominations are open. {who}{ineligible}{primary}"
            "nominate a seated member (self is allowed unless ineligible) and include a platform that "
            "names a goal and a file you would produce. vote_election is inert. "
            "You cannot nominate someone who is not seated. "
            "If you are President, you may still write_workspace toward current goals."
        )
        digest = digest_for_card(digest, exclude_member=member_id)
    elif prez and prez != "(vacant)":
        vacant = _goals_empty(goals_md) or " invalid " in f" {goal_clock} "
        if vacant:
            prez_spoke = any(
                str(line).startswith(f"**{prez}:**") for line in (current_speeches or [])
            )
            if member_id == prez:
                duty = (
                    "You are President. executive set_goal this turn and write_workspace. "
                    "Do not impeach yourself for an empty register you can still fill."
                )
                if gov.get("policy_due"):
                    duty += (
                        " policy_due: also executive edit_policy this turn with the full "
                        "revised nation policy (same executive list is fine)."
                    )
            elif prez_spoke:
                duty = (
                    f"{prez} already spoke and the register is still empty. "
                    "Impeach with a cited article (207). Do not add_member."
                )
            else:
                duty = (
                    f"{prez} still acts this turn. Do not impeach for empty goals until "
                    "they have spoken. If they leave the register empty, cite 207 after "
                    "they act or next turn. Do not add_member."
                )
            host_truth = (
                f"HOST: the election is over. {prez} is President. Goals are empty or invalid — failure. "
                "This nation needs a goal someone can fail, not a speech fragment. "
                "Repeal an invalid id or replace it with goalN and a real objective. "
                "nominate and vote_election do nothing this turn. "
                f"{duty} "
                "If you announce a bill, put it in propose with effects."
            )
        else:
            host_truth = (
                f"HOST: the election is over. {prez} is President. "
                "Grow the nation: finish or replace the live goal, contest the next term, "
                "file proof (body must name a live goal id), seat someone if the work needs them. "
                "nominate and vote_election do nothing this turn. "
                "If you announce a bill, put it in propose with effects. "
                "If you are President, use executive (set_goal or write_workspace) this turn."
            )
            if member_id == prez and gov.get("policy_due"):
                host_truth += (
                    " policy_due: executive edit_policy this turn with the full revised "
                    "document. Fold your campaign in; do not leave the seed blank."
                )
            if goal_clock:
                host_truth += (
                    f" Goals: {goal_clock}. "
                    "A file counts only if it names that goal's id and was written after "
                    "the goal was set. Repeal only a complete, overdue, or invalid goal."
                )
        digest = digest_for_card(digest, exclude_member=member_id)
    else:
        host_truth = "HOST: presidency vacant. First business is nominations."
        digest = digest_for_card(digest, exclude_member=member_id)
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
    if seat_nudge:
        host_truth += (
            " Grow a vote: add_member who will sit with a caucus, or whisper "
            "an unaffiliated colleague. Do not seat a clerk to write files."
        )
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
    papers = ""
    if office_papers.strip() and member_id == prez:
        papers = f"\n{office_papers.strip()}\n"
    inbox = (whispers_md or "").strip()
    inbox_block = f"\n{inbox}\n" if inbox else ""
    treasury_block = ""
    if (treasury_md or "").strip():
        treasury_block = f"\n{treasury_md.strip()}\n"
    standing_block = ""
    if (standing_md or "").strip():
        standing_block = f"\n{standing_md.strip()}\n"
    committee_block = ""
    if (committee_md or "").strip():
        committee_block = f"\n{committee_md.strip()}\n"
    questions_block = ""
    if (questions_md or "").strip():
        questions_block = f"\n{questions_md.strip()}\n"
    opposition_block = ""
    if (opposition_md or "").strip():
        opposition_block = f"\n{opposition_md.strip()}\n"
    term_block = ""
    if (term_md or "").strip():
        term_block = f"\n{term_md.strip()}\n"
    session_block = ""
    if (session_md or "").strip():
        session_block = f"\n{session_md.strip()}\n"
    current_floor = "\n".join(current_speeches or []).strip() or "(you speak first)"
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
{papers}{inbox_block}{treasury_block}{standing_block}{committee_block}{questions_block}{opposition_block}{term_block}{session_block}
Earlier this turn (these citizens have already spoken; answer them when relevant):
{current_floor}

Other citizens last turn (your own line is already in your private act history):
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


def _usable_act(
    data: dict[str, Any],
    required: str | None = None,
    *,
    policy_due: bool = False,
) -> bool:
    if required == "executive" and policy_due:
        from adags.effects import coerce_effects

        if data.get("edit_policy") is not None:
            return True
        return any(
            isinstance(fx, dict) and fx.get("type") == "edit_policy"
            for fx in coerce_effects(data.get("executive"))
        )
    if required:
        return bool(data.get(required))
    return bool(str(data.get("speech") or "").strip()) or bool(
        data.get("nominate")
        or data.get("vote_election")
        or data.get("impeach")
        or data.get("propose")
        or data.get("vote_motion")
        or data.get("executive")
        or data.get("edit_policy") is not None
        or data.get("whisper") not in (None, False)
        or data.get("party") is not None
    )


def citizen_act(
    llm: LLM,
    *,
    member: dict,
    user: str,
    on_token=None,
    on_think=None,
    president: bool = False,
    members: list[dict] | None = None,
    gov: dict | None = None,
    goals_empty: bool = False,
    required: str | None = None,
    policy_due: bool = False,
) -> dict[str, Any]:
    system = CITIZEN_SYSTEM.format(
        member_id=member["id"],
        values=member["values"],
        party_line=party_line(member, members or [member], gov),
    )
    token_budget = 1600 if policy_due else 512
    raw = llm.complete(
        system=system,
        user=user,
        on_token=on_token,
        on_think=on_think,
        prefix=ACT_PREFIX,
        max_tokens=token_budget,
    )
    data, parse_error = _parse_act(raw.text)
    data = fulfill_speech(data, member_id=member["id"], president=president)
    timed_out_empty = bool(raw.error) and not str(raw.text or "").strip()
    if not _usable_act(data, required, policy_due=policy_due) and not timed_out_empty:
        requirement = (
            " Fill `executive` with edit_policy and the full revised nation policy."
            if required == "executive" and policy_due
            else f" Fill `{required}` with a real structured act."
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
                llm.timeout = min(float(saved[0]), 20.0)
            if saved[1] is not None:
                llm.think_timeout = min(float(saved[1]), 10.0)
            if saved[2] is not None:
                llm.first_token_timeout = min(float(saved[2]), 12.0)
            raw2 = llm.complete(
                system=system,
                user=(
                    f"You are {member.get('id')}. "
                    + _REPAIR_USER
                    + requirement
                    + " Do not recap the card."
                ),
                on_token=on_token,
                on_think=on_think,
                prefix=ACT_PREFIX,
                max_tokens=token_budget,
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
        if _usable_act(data2, required, policy_due=policy_due):
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
    if protocol_speech(data["speech"]):
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

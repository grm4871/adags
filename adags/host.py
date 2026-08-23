"""Turn loop: elections, executive privilege, legislation, membership."""

from __future__ import annotations

import json
import random
import time
from datetime import datetime
from typing import Any

from adags.brief import brief_every, maybe_clerk_brief
from adags.citizens import citizen_act, clerk_compile, snapshot_user
from adags.policy import campaign_text, ensure_policy, policy_card
from adags.whispers import (
    append_log,
    format_inbox,
    format_whisper_log,
    load_hold,
    parse_whisper,
    save_hold,
)
from adags.relations import format_standing, update_from_act
from adags.treasury import card as treasury_card
from adags.treasury import gate_add_member, init as treasury_init, settle as treasury_settle
from adags import committees as committees_mod
from adags import questions as questions_mod
from adags import terms as terms_mod
from adags.opposition import opposition_card, opposition_id
from adags.constitution import apply_to_runtime, identical_charter_line, value
from adags.memory import (
    append_record,
    compose_user,
    goal_clock,
    load_records,
    patch_last_record,
    record_from_act,
    workspace_card,
)
from adags.effects import (
    apply_effect,
    apply_inverse,
    coerce_effects,
    bill_title,
    complete_set_goal,
    goals_are_vacant,
    inert_motion_note,
    path_in_prose,
    propose_effects,
    render_goals,
)
from adags.gov import (
    add_nominee,
    advance_phase,
    apply_caucus_ballot,
    apply_party,
    as_impeach,
    as_member_id,
    as_party_id,
    consecutive_blocked,
    election_due,
    member_ids,
    passes,
    plurality_winner,
    president_id,
    seat_president,
    seat_summary,
    threshold,
    vacate_president,
)
from adags.llm import LLM
from adags.render import (
    ChamberVoice,
    as_ballot,
    c,
    citizen_close,
    citizen_open,
    emit,
    format_votes,
    member_parties,
    turn_close,
    turn_open,
    wrap_field,
)
from adags.state import RunState


def _meter(control: dict, usage: dict | None) -> None:
    if not usage:
        return
    control["usd_spent"] = float(control.get("usd_spent") or 0) + float(usage.get("usd") or 0)
    control["input_tokens"] = int(control.get("input_tokens") or 0) + int(usage.get("input_tokens") or 0)
    control["output_tokens"] = int(control.get("output_tokens") or 0) + int(usage.get("output_tokens") or 0)


def _log(msg: str) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    print(f"{now}  {msg}", flush=True)


def _budget_ok(control: dict) -> bool:
    if control.get("paused"):
        return False
    if int(control["turn"]) > int(control["turn_cap"]):
        return False
    if float(control["usd_spent"]) >= float(control["usd_cap"]):
        return False
    return True


def speaking_order(
    members: list[dict],
    saved: list[str] | None = None,
    *,
    shuffle=None,
) -> list[dict]:
    """Choose a turn order, or reconstruct the order persisted at checkpoint."""
    by_id = {str(member.get("id")): member for member in members}
    if saved and len(saved) == len(by_id) and set(saved) == set(by_id):
        return [by_id[member_id] for member_id in saved]
    ordered = list(members)
    (shuffle or random.SystemRandom().shuffle)(ordered)
    return ordered


def authorize_operator_turns(
    control: dict,
    *,
    turns: int | None,
    turn_cap: int | None = None,
) -> int | None:
    """Unpause. Asking for turns is consent to raise the ceiling to fit them.

    A bare run after the clock already expired counts as one more turn.
    Returns how many turns this invocation should play (`None` = until cap).
    """
    control["paused"] = False
    if turn_cap is not None:
        control["turn_cap"] = int(turn_cap)
    play = turns
    nxt = int(control["turn"])
    cap = int(control["turn_cap"])
    if play is None and nxt > cap:
        play = 1
    if play is not None and play > 0:
        needed = nxt + int(play) - 1
        if needed > cap:
            control["turn_cap"] = needed
    return play


def _open_motion(state: RunState) -> dict | None:
    p = state.root / "motions" / "open.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _write_open_motion(state: RunState, motion: dict | None) -> None:
    p = state.root / "motions" / "open.json"
    if motion is None:
        if p.exists():
            p.unlink()
        return
    p.write_text(json.dumps(motion, indent=2) + "\n", encoding="utf-8")


def _apply_many(
    state: RunState,
    effects: list[dict],
    *,
    actor: str | None,
    source: str,
    act_id: str,
    committee_gate=None,
) -> list[str]:
    law = state.law()
    goals = state.goals()
    members = state.members()
    gov = state.gov()
    # Insolvency gate: the host refuses to seat new members it cannot pay.
    if any(isinstance(e, dict) and e.get("type") == "add_member" for e in effects):
        refusal = gate_add_member(state.root, law=law)
        if refusal:
            return [refusal]
    inverses = []
    notes = []
    applied = False
    for effect in effects:
        result, inverse = apply_effect(
            effect,
            law=law,
            goals=goals,
            members=members,
            gov=gov,
            workspace=state.workspace,
            turn=state.control()["turn"],
            actor=actor,
            source=source,
            committee_gate=committee_gate,
        )
        notes.append(result.get("note", ""))
        if not result.get("ok"):
            continue
        applied = True
        # Term record: set_goal texts are promises; written files are delivery.
        if source == "executive" and actor:
            if effect.get("type") == "set_goal":
                terms_mod.add_promise(
                    state.root, holder=actor, text=str(effect.get("text") or "")
                )
            elif effect.get("type") == "write_workspace":
                from adags.effects import _resolve_write_fields, _safe_relpath

                probe = _resolve_write_fields(dict(effect))
                rel_done = _safe_relpath(str(probe.get("path") or ""))
                if rel_done:
                    terms_mod.mark_delivered(
                        state.root, holder=actor, rel_path=rel_done
                    )
        if "law" in result:
            law = result["law"]
            state.write_law(law)
            gov = apply_to_runtime(gov, law)
            state.write_gov(gov)
        if "goals" in result:
            goals = result["goals"]
            state.write_goals(goals)
        if result.get("goals_meta"):
            meta = state.goals_meta()
            meta.update(result["goals_meta"])
            state.write_goals_meta(meta)
        if result.get("goals_meta_remove"):
            meta = state.goals_meta()
            meta.pop(str(result["goals_meta_remove"]), None)
            state.write_goals_meta(meta)
        if "members" in result:
            members = result["members"]
            state.write_members(members)
        if "gov" in result:
            gov = result["gov"]
            state.write_gov(gov)
        if inverse:
            inverses.append(inverse)
    if applied:
        state.append_act(
            {
                "id": act_id,
                "source": source,
                "actor": actor,
                "effects": effects,
                "inverses": inverses,
                "vetoed": False,
            }
        )
        control = state.control()
        control["last_act_id"] = act_id
        state.write_control(control)
    return notes


def _load_ballots(gov: dict) -> dict[str, str]:
    if gov.get("election_phase") != "ballot":
        return {}
    out: dict[str, str] = {}
    for who, pick in (gov.get("ballots") or {}).items():
        mid = as_member_id(pick)
        if mid:
            out[str(who)] = mid
    return out


def _format_election_votes(votes: dict[str, str]) -> str:
    if not votes:
        return "none"
    return ", ".join(f"{who}→{pick}" for who, pick in votes.items())


def _format_impeach_marks(votes: list[str], charges: dict[str, str]) -> str:
    if not votes:
        return "none"
    bits = []
    for mid in votes:
        art = (charges or {}).get(mid)
        bits.append(f"{mid} ({art})" if art else mid)
    return ", ".join(bits)


def _load_turn_progress(state: RunState, turn: int) -> dict:
    path = state.root / "turn_progress.json"
    if not path.exists():
        return {"turn": turn, "completed": [], "speeches": [], "impeach_votes": [], "exec_notes": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("turn") != turn:
        return {"turn": turn, "completed": [], "speeches": [], "impeach_votes": [], "exec_notes": []}
    return data


def _write_turn_progress(state: RunState, progress: dict) -> None:
    state.dump_json("turn_progress.json", progress)


def _clear_turn_progress(state: RunState) -> None:
    path = state.root / "turn_progress.json"
    if path.exists():
        path.unlink()


def _motion_threshold(law: dict, motion: dict, gov: dict) -> str:
    """Floor set_goal/write_workspace uses offices.president.override when set."""
    override = value(law, "offices.president.override")
    if override:
        for fx in coerce_effects(motion.get("effects")):
            if (fx or {}).get("type") == "write_workspace":
                return str(override)
    return str(gov.get("vote_rule") or value(law, "motion.threshold", "majority"))


def _enact_motion(
    state: RunState,
    llm: LLM,
    control: dict,
    motion: dict,
    votes: dict,
    *,
    committee_gate=None,
) -> list[str]:
    """Apply structured effects; if none take, let the clerk compile the text."""
    notes: list[str] = []
    act_id = str(motion.get("id") or "motion")
    actor = motion.get("proposer")
    effects = [e for e in (motion.get("effects") or []) if isinstance(e, dict)]
    if effects:
        notes.extend(_apply_many(state, effects, actor=actor, source="motion", act_id=act_id))
    if state.control().get("last_act_id") != act_id:
        llm.remaining_usd = max(
            0.0,
            float(control["usd_cap"]) - float(control["usd_spent"]),
        )
        compiled = clerk_compile(
            llm,
            constitution=state.constitution(),
            motion=motion,
            votes=votes,
        )
        _meter(control, compiled.get("_usage"))
        state.write_control(control)
        notes.append(f"clerk: {compiled.get('reason')}")
        extra = [e for e in (compiled.get("effects") or []) if isinstance(e, dict)]
        if compiled.get("compiled") and extra:
            notes.extend(_apply_many(state, extra, actor=actor, source="motion", act_id=act_id))
    if state.control().get("last_act_id") != act_id:
        notes.append("passed with no host effects")
    return notes


def veto_last(state: RunState) -> str:
    act = state.last_act()
    if not act or act.get("vetoed"):
        return "nothing to veto"
    law = state.law()
    goals = state.goals()
    members = state.members()
    gov = state.gov()
    for inverse in reversed(act.get("inverses") or []):
        result = apply_inverse(
            inverse,
            law=law,
            goals=goals,
            members=members,
            gov=gov,
            workspace=state.workspace,
            turn=state.control()["turn"],
        )
        if "law" in result:
            law = result["law"]
            state.write_law(law)
        if "goals" in result:
            goals = result["goals"]
            state.write_goals(goals)
        if result.get("goals_meta"):
            meta = state.goals_meta()
            meta.update(result["goals_meta"])
            state.write_goals_meta(meta)
        if result.get("goals_meta_remove"):
            meta = state.goals_meta()
            meta.pop(str(result["goals_meta_remove"]), None)
            state.write_goals_meta(meta)
        if "members" in result:
            members = result["members"]
            state.write_members(members)
        if "gov" in result:
            gov = result["gov"]
            state.write_gov(gov)
    act["vetoed"] = True
    # rewrite last line is messy; journal the veto and mark control
    state.append_act({**act, "id": act["id"] + ":veto-scar"})
    state.append_journal(f"\n## VETO of {act['id']}\nOperator reversed reversible effects.\n")
    return f"vetoed {act['id']}"


def run_turn(state: RunState, llm: LLM, *, deadline: float | None = None) -> str:
    control = state.control()
    if not _budget_ok(control):
        control["paused"] = True
        state.write_control(control)
        return "paused (cap or flag)"

    turn = int(control["turn"])
    law = state.law()
    motion = _open_motion(state)
    gov = advance_phase(
        apply_to_runtime(state.gov(), law),
        turn,
        motion_open=motion is not None,
    )
    election_votes = _load_ballots(gov)
    gov["ballots"] = dict(election_votes)
    state.write_gov(gov)
    members = state.members()
    constitution = state.constitution()
    goals = state.goals()
    vacant = goals_are_vacant(goals)
    register_was_empty = vacant
    digest = state.last_digest()
    petitions = state.petitions()
    clock = goal_clock(goals, state.workspace, turn, meta=state.goals_meta())
    identical = identical_charter_line(law)
    unaffiliated = [m for m in members if not str(m.get("party") or "").strip()]
    seat_nudge = bool(
        (election_due(gov, turn) or gov.get("election_phase") in {"nominate", "ballot"})
        and len(members) < 10
    ) or (len(unaffiliated) >= 1 and len(members) <= 7)

    progress = _load_turn_progress(state, turn)
    floor = speaking_order(
        members,
        progress.get("speaking_order"),
        shuffle=(lambda _members: None)
        if getattr(llm, "preserve_member_order", False)
        else None,
    )
    progress["speaking_order"] = [member["id"] for member in floor]
    _write_turn_progress(state, progress)
    speeches: list[str] = list(progress.get("speeches") or [])
    impeach_votes: list[str] = list(progress.get("impeach_votes") or [])
    impeach_charges: dict[str, str] = dict(progress.get("impeach_charges") or {})
    exec_notes: list[str] = list(progress.get("exec_notes") or [])
    completed = set(progress.get("completed") or [])
    inbox: dict[str, list[dict]] = {
        str(mid): list(notes)
        for mid, notes in (progress.get("inbox") or {}).items()
        if isinstance(notes, list)
    }
    if not inbox and not completed:
        inbox = load_hold(state.root)
        save_hold(state.root, {})
    whispered: list[dict] = list(progress.get("whispers") or [])
    late_hold: dict[str, list[dict]] = {
        str(mid): list(notes)
        for mid, notes in (progress.get("late_hold") or {}).items()
        if isinstance(notes, list)
    }
    questions_this_turn: list[dict] = []
    questions_late: dict[str, list[dict]] = {}
    question_inbox: dict[str, list[dict]] = {
        str(mid): list(notes)
        for mid, notes in (progress.get("question_inbox") or {}).items()
        if isinstance(notes, list)
    }
    if not question_inbox and not completed:
        question_inbox = questions_mod.load_hold(state.root)
        questions_mod.save_hold(state.root, {})
    interrupted = False
    n_members = len(members)
    law_now = state.law()
    treasury_init(state.root, law=law_now)
    # Term rhythm: how many turns until the next election is due.
    prez_now = president_id(gov)
    term_start = ((gov.get("offices") or {}).get("president") or {}).get("term_start")
    term_len = int(gov.get("term_length") or 8)
    turns_to_election = (
        max(0, int(term_start) + term_len - turn)
        if prez_now and term_start is not None
        else 0
    )
    session_note = ""
    if prez_now and turns_to_election:
        if turns_to_election <= 2:
            session_note = (
                f"SESSION: election is due in {turns_to_election} turn(s). "
                "Campaigns, deals, and last pushes happen now."
            )
        else:
            session_note = f"Session {turns_to_election} turns before the next election."
    relations_file = state.root / "relations.json"
    try:
        relations = json.loads(relations_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        relations = {}
    if not isinstance(relations, dict):
        relations = {}

    def _party_of(mid: str) -> str:
        for m in members:
            if m.get("id") == mid:
                return str(m.get("party") or "")
        return ""

    def _member_committee_md(mid: str) -> str:
        cards = committees_mod.committee_card(state.root)
        mine = committees_mod.memberships_for(state.root, mid)
        if not mine:
            return cards
        bits = "; ".join(
            f"{c['name']}" + (" (chair)" if c["chair"] else "") for c in mine
        )
        return f"{cards}\nYou serve on: {bits}."

    def _committee_gate(rel_path: str, mid: str) -> str | None:
        return committees_mod.gate_write(
            state.root, rel_path, mid, president=president_id(state.gov())
        )

    question_inbox = questions_mod.load_hold(state.root)

    turn_open(turn=turn, gov=gov, n_members=n_members, motion=motion, members=members)

    for member in floor:
        if member["id"] in completed:
            continue
        if deadline is not None and time.monotonic() >= deadline:
            interrupted = True
            break
        llm.deadline = deadline
        llm.remaining_usd = max(
            0.0,
            float(control["usd_cap"]) - float(control["usd_spent"]),
        )
        prior = load_records(state.root, member["id"])
        papers = ""
        if member["id"] == (president_id(gov) or ""):
            papers = policy_card(
                policy=ensure_policy(state.root),
                campaign=campaign_text(state.workspace, member["id"]),
                due=bool(gov.get("policy_due")),
                editor=gov.get("policy_editor"),
                edited_turn=gov.get("policy_edited_turn"),
            )
        snapshot = snapshot_user(
            member_id=member["id"],
            constitution=constitution,
            gov=gov,
            members=members,
            goals_md=render_goals(goals),
            open_motion=motion,
            digest=digest,
            petitions=petitions,
            turn=turn,
            workspace_md=workspace_card(state.workspace),
            current_speeches=speeches,
            goal_clock=clock,
            identical_line=identical,
            seat_nudge=seat_nudge,
            office_papers=papers,
            whispers_md=format_inbox(inbox.get(member["id"]) or []),
            treasury_md=treasury_card(state.root, law=law_now, n_members=len(members)),
            standing_md=format_standing(relations, member["id"], member_ids(members)),
            committee_md=_member_committee_md(member["id"]),
            questions_md=questions_mod.format_inbox(
                question_inbox.get(member["id"]) or []
            ),
            opposition_md=opposition_card(members, gov, member_id=member["id"]),
            term_md=terms_mod.card(state.root),
            session_md=session_note,
        )
        user = compose_user(load_records(state.root, member["id"]), snapshot)
        citizen_open(member["id"], party=str(member.get("party") or "") or None)
        voice = ChamberVoice()
        t0 = time.monotonic()
        act = citizen_act(
            llm,
            member=member,
            user=user,
            gov=gov,
            on_token=voice.feed,
            on_think=voice.feed_think,
            president=member["id"] == (president_id(gov) or ""),
            members=members,
            goals_empty=vacant,
            policy_due=bool(
                member["id"] == (president_id(gov) or "") and gov.get("policy_due")
            ),
            required=(
                "vote_motion"
                if motion is not None
                else "vote_election"
                if gov.get("election_phase") == "ballot"
                else "nominate"
                if gov.get("election_phase") == "nominate"
                else "executive"
                if member["id"] == (president_id(gov) or "")
                and (vacant or gov.get("policy_due"))
                else None
            ),
        )
        spoke = voice.finish()
        elapsed = time.monotonic() - t0
        _meter(control, act.get("_usage"))
        state.write_control(control)
        speech = act.get("speech") or "(silent)"
        speeches.append(f"**{member['id']}:** {speech}")
        usage = act.get("_usage") or {}
        raw_dir = state.root / "raw"
        raw_dir.mkdir(exist_ok=True)
        (raw_dir / f"t{turn}-{member['id']}.txt").write_text(usage.get("raw") or "", encoding="utf-8")
        citizen_close(
            act,
            elapsed=elapsed,
            spoke=spoke,
            phase=str(gov.get("election_phase") or ""),
            seated=member_ids(members),
            parties=member_parties(members),
        )
        host_bits: list[str] = []
        inbox.pop(member["id"], None)

        if act.get("party") is not None:
            slug = as_party_id(act.get("party"))
            if slug is not None:
                members = apply_party(members, member["id"], slug)
                state.write_members(members)
                speeches.append(
                    f"- {'joined ' + slug if slug else 'left party'} ({member['id']})"
                )

        got = parse_whisper(
            act.get("whisper"),
            sender=member["id"],
            seated=member_ids(members),
        )
        if isinstance(got, dict):
            whispered.append(got)
            append_log(state.root, turn, got)
            target = str(got["to"])
            if target in completed:
                late_hold.setdefault(target, []).append(got)
            else:
                inbox.setdefault(target, []).append(got)
            host_bits.append(f"whisper {target}")
            emit(c("35", f"  whisper → {target}: {got['body']}"))
        elif isinstance(got, str):
            host_bits.append(got)

        # Public questions: routed to the target's next card; logged in digest.
        asked = questions_mod.parse_question(
            act.get("question"),
            sender=member["id"],
            seated=member_ids(members),
        )
        if isinstance(asked, dict):
            questions_this_turn.append(asked)
            target = str(asked["to"])
            if target in completed:
                questions_late.setdefault(target, []).append(asked)
            else:
                question_inbox.setdefault(target, []).append(asked)
            host_bits.append(f"question to {target}")
            emit(c("35", f"  question → {target}: {asked['body']}"))
            speeches.append(f"- asks {target}: {asked['body'][:80]}")
        elif isinstance(asked, str):
            host_bits.append(asked)

        nom = act.get("nominate")
        if isinstance(nom, dict) and gov.get("election_phase") == "nominate":
            target = as_member_id(nom.get("member")) or as_member_id(nom)
            if target in member_ids(members):
                from adags.llm import protocol_speech

                plat = str(nom.get("platform") or "")
                if protocol_speech(plat) or plat.count("\n") >= 2:
                    plat = "short platform"
                updated = add_nominee(
                    gov,
                    member=target,
                    platform=plat,
                    nominator=member["id"],
                    turn=turn,
                    members=members,
                    caucus_primary=bool(gov.get("caucus_primary", True)),
                )
                if isinstance(updated, str):
                    host_bits.append(updated)
                    if updated.startswith("seconded "):
                        speeches.append(f"- {updated}")
                else:
                    gov = updated
                    state.write_gov(gov)
                    filed = (gov.get("nominees") or [])[-1]["member"]
                    dest = state.workspace / "platforms" / f"{filed}.md"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(f"# Platform: {filed}\n\n{plat}\n", encoding="utf-8")
                    speeches.append(f"- nominated {filed}")
                    host_bits.append(f"nominated {filed}")
            else:
                host_bits.append("nominate ignored (not seated)")
        elif isinstance(nom, dict) and gov.get("election_phase") != "nominate":
            host_bits.append(f"nominate ignored ({gov.get('election_phase')})")

        vote_e = as_member_id(act.get("vote_election"))
        if vote_e and gov.get("election_phase") == "ballot":
            vote_e, remap_note = apply_caucus_ballot(
                member["id"],
                vote_e,
                members,
                gov,
                caucus_primary=bool(gov.get("caucus_primary", True)),
            )
            if remap_note:
                host_bits.append(remap_note)
        nominees = {n.get("member") for n in (gov.get("nominees") or [])}
        blocked = consecutive_blocked(gov)
        if vote_e and gov.get("election_phase") == "ballot":
            if blocked and vote_e == blocked:
                host_bits.append(f"vote_election ignored ({vote_e} ineligible this election)")
            elif vote_e in nominees:
                election_votes[member["id"]] = vote_e
                gov["ballots"] = dict(election_votes)
                state.write_gov(gov)
                host_bits.append(f"ballot {vote_e}")
            else:
                host_bits.append(f"vote_election ignored (not a nominee)")
        elif vote_e:
            host_bits.append(f"vote_election ignored ({gov.get('election_phase')})")

        marked, article = as_impeach(act.get("impeach"))
        if marked and article:
            if member["id"] not in impeach_votes:
                impeach_votes.append(member["id"])
            impeach_charges[member["id"]] = article
            host_bits.append(f"impeach {article}")
        elif marked:
            host_bits.append("impeach ignored (cite an article)")

        if motion is None:
            prop = act.get("propose")
            effects = propose_effects(prop)
            if isinstance(prop, dict) and (
                prop.get("title") or prop.get("text") or prop.get("effects") or effects
            ) and gov.get("election_phase") in {"nominate", "ballot"}:
                host_bits.append(
                    f"propose ignored ({gov.get('election_phase')} — finish the election)"
                )
            elif isinstance(prop, dict) and (
                prop.get("title") or prop.get("text") or prop.get("effects") or effects
            ):
                if not effects:
                    effects = list(prop.get("effects") or [])
                blocked = inert_motion_note(
                    effects,
                    law=state.law(),
                    goals=state.goals(),
                    members=state.members(),
                    gov=gov,
                )
                if blocked:
                    host_bits.append(blocked)
                else:
                    # Opposition privilege: the leader's motion is marked as
                    # official opposition business in the journal.
                    if member["id"] == opposition_id(members, gov):
                        speeches.append(
                            f"- opposition motion (Leader {member['id']})"
                        )
                    title = bill_title(
                        title=str(prop.get("title") or ""),
                        text=str(prop.get("text") or ""),
                        effects=effects,
                        speech=str(act.get("speech") or ""),
                    )
                    motion = {
                        "id": f"m{turn}-{member['id']}",
                        "title": title,
                        "text": str(prop.get("text") or ""),
                        "effects": effects,
                        "proposer": member["id"],
                        "votes": {member["id"]: "aye"},
                    }
                    _write_open_motion(state, motion)
                    for line in wrap_field("bill", motion["title"]):
                        emit(line)
                    for line in wrap_field("votes", format_votes(motion.get("votes"), member_parties(members))):
                        emit(line)
                    host_bits.append(f"opened {motion['id']}")
        else:
            vm = as_ballot(act.get("vote_motion"))
            if vm:
                motion.setdefault("votes", {})[member["id"]] = vm
                _write_open_motion(state, motion)
                for line in wrap_field("votes", format_votes(motion.get("votes"), member_parties(members))):
                    emit(line)
                host_bits.append(f"{vm} on {motion.get('id')}")

        exec_fx = coerce_effects(act.get("executive"))
        for key in ("set_goal", "write_workspace", "edit_policy"):
            if act.get(key) is not None:
                exec_fx.extend(coerce_effects({key: act[key]}))
        spoken = str(act.get("speech") or "")
        for fx in exec_fx:
            if not isinstance(fx, dict):
                continue
            if fx.get("type") == "set_goal":
                complete_set_goal(fx, speech=spoken)
            elif fx.get("type") == "write_workspace":
                if not fx.get("path") or fx.get("path") == "design-log.md":
                    found = path_in_prose(spoken)
                    if found:
                        fx["path"] = found
        if exec_fx:
            allowed = []
            for fx in exec_fx:
                kind = (fx or {}).get("type")
                privileges = value(state.law(), "offices.president.privileges", []) or []
                if member["id"] == president_id(gov) and (
                    kind in privileges or kind == "edit_policy"
                ):
                    allowed.append(fx)
                else:
                    exec_notes.append(f"{member['id']} executive {kind} dropped (no privilege)")
                    host_bits.append(f"{kind} dropped (no privilege)")
            if allowed:
                notes = _apply_many(
                    state,
                    allowed,
                    actor=member["id"],
                    source="executive",
                    act_id=f"t{turn}-{member['id']}-exec",
                    committee_gate=_committee_gate,
                )
                exec_notes.extend(notes)
                host_bits.extend(str(n) for n in notes if n)
                # refresh after executive
                gov = apply_to_runtime(state.gov(), state.law())
                state.write_gov(gov)
                members = state.members()
                constitution = state.constitution()
                goals = state.goals()
                vacant = goals_are_vacant(goals)

        update_from_act(
            relations,
            actor=member["id"],
            act=act,
            seated=member_ids(members),
            president=president_id(gov),
            member_party_of=_party_of,
        )
        try:
            relations_file.write_text(json.dumps(relations, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

        rec = record_from_act(turn, act)
        if host_bits:
            rec["host"] = "; ".join(host_bits)[:360]
        append_record(state.root, member["id"], rec)

        completed.add(member["id"])
        progress.update(
            {
                "completed": sorted(completed),
                "speeches": speeches,
                "impeach_votes": impeach_votes,
                "impeach_charges": impeach_charges,
                "exec_notes": exec_notes,
                "inbox": inbox,
                "question_inbox": {
                    k: v for k, v in question_inbox.items() if v
                },
                "whispers": whispered,
                "late_hold": late_hold,
            }
        )
        _write_turn_progress(state, progress)
        if not _budget_ok(control):
            interrupted = True
            break

    save_hold(state.root, late_hold)
    questions_mod.save_hold(
        state.root,
        {
            **{k: v for k, v in question_inbox.items() if v},
            **{k: v for k, v in questions_late.items() if v},
        },
    )
    if interrupted:
        return f"turn {turn} checkpointed after {len(completed)}/{len(members)} citizens"

    # Treasury settles once per turn, after all acts and effects.
    treasury_notes = treasury_settle(
        state.root,
        law=state.law(),
        turn=turn,
        n_members=len(state.members()),
        goals=state.goals(),
        goal_clock_text=goal_clock(state.goals(), state.workspace, turn, meta=state.goals_meta()),
    )

    # Impeach
    n = len(state.members())
    impeached = False
    dropped_207: list[str] = []
    if register_was_empty and state.goals():
        dropped_207 = [mid for mid in impeach_votes if impeach_charges.get(mid) == "207"]
        impeach_votes = [mid for mid in impeach_votes if mid not in set(dropped_207)]
    if value(state.law(), "impeachment.enabled", True) and impeach_votes and passes(len(impeach_votes), n, gov.get("impeach_threshold") or "majority"):
        gov = vacate_president(gov)
        state.write_gov(gov)
        terms_mod.close_term(state.root, turn=turn)
        impeached = True

    # Ballot
    seated = None
    seat_note = ""
    ballot_noms = list(gov.get("nominees") or [])
    if gov.get("election_phase") == "ballot":
        winner = plurality_winner(election_votes, ballot_noms)
        quorum = threshold(value(state.law(), "election.quorum", "majority"), n)
        blocked = consecutive_blocked(gov)
        if winner and blocked and winner == blocked:
            winner = None
        if winner and len(election_votes) >= quorum:
            # A term ends when a successor is seated: grade the outgoing record.
            closed_rec = terms_mod.close_term(state.root, turn=turn)
            if closed_rec is not None:
                speeches.append(
                    f"- term record {closed_rec.get('holder')}: "
                    f"platform \"{(closed_rec.get('platform') or '')[:80]}\" "
                    f"scored {closed_rec.get('score')}"
                )
            seat_note = seat_summary(election_votes, ballot_noms, winner)
            gov = seat_president(gov, winner, turn)
            state.write_gov(gov)
            seated = winner
            platform = next(
                (
                    str(nom.get("platform") or "")
                    for nom in ballot_noms
                    if nom.get("member") == winner
                ),
                "",
            )
            terms_mod.open_term(state.root, holder=winner, turn=turn, platform=platform)

    # Motion resolution
    motion_notes: list[str] = []
    if motion:
        votes = motion.get("votes") or {}
        ayes = sum(1 for v in votes.values() if v == "aye")
        decisive = value(state.law(), "motion.resolve_when", "decisive") == "decisive"
        rule = _motion_threshold(state.law(), motion, gov)
        decided = set(votes) >= set(member_ids(state.members())) or (
            decisive and ayes >= threshold(rule, n)
        )
        # resolve if everyone voted, or enough ayes, or enough nays to make pass impossible
        nays = sum(1 for v in votes.values() if v == "nay")
        need = threshold(rule, n)
        if decided or (decisive and nays > n - need):
            passed = passes(ayes, n, rule)
            if passed:
                motion_notes.extend(
                    _enact_motion(state, llm, control, motion, votes, committee_gate=_committee_gate)
                )
            else:
                motion_notes.append("motion failed")
            closed = state.root / "motions" / f"{motion['id']}.json"
            closed.write_text(json.dumps({**motion, "passed": passed}, indent=2) + "\n", encoding="utf-8")
            proposer = str(motion.get("proposer") or "")
            if proposer:
                result = "passed" if passed else "failed"
                detail = "; ".join(str(n) for n in motion_notes if n) or result
                patch_last_record(
                    state.root,
                    proposer,
                    turn,
                    host=f"bill {result} {ayes}-{nays}: {detail}",
                )
            _write_open_motion(state, None)
            motion = None

    digest_lines = [
        f"# Turn {turn} digest",
        f"President: {president_id(state.gov()) or '(vacant)'}",
        f"Phase: {state.gov().get('election_phase')}",
        f"Seated: {', '.join(member_ids(state.members()))}",
        f"Speaking order: {', '.join(member['id'] for member in floor)}",
        "",
        "## Speech",
        *speeches,
        "",
        f"Impeach marks: {_format_impeach_marks(impeach_votes, impeach_charges)}"
        + (" — VACATED" if impeached else "")
        + (
            f" — 207 marks ignored (register filled this turn): {', '.join(dropped_207)}"
            if dropped_207
            else ""
        ),
        f"Election votes: {_format_election_votes(election_votes)}"
        + (
            f" — {seat_note}"
            if seated
            else (
                " — still open, no seat"
                if state.gov().get("election_phase") == "ballot"
                else ""
            )
        ),
        f"Whispers: {format_whisper_log(whispered)}",
        f"Questions: {questions_mod.log_line(questions_this_turn)}",
        *(
            [f"Treasury: {note}" for note in treasury_notes]
            if treasury_notes
            else ["Treasury: (settled, no entries)"]
        ),
        "## Executive",
        *(exec_notes or ["(none)"]),
        "## Motion",
        *(motion_notes or [("(open) " + motion["title"]) if motion else "(none)"]),
    ]
    mechanical = "\n".join(digest_lines) + "\n"
    brief = maybe_clerk_brief(state, turn=turn, mechanical=mechanical)
    digest_text = mechanical
    if brief:
        start = max(1, int(turn) - max(brief_every(), 1) + 1)
        digest_text = (
            f"# Clerk brief (turns {start}–{turn})\n\n{brief}\n\n---\n\n{mechanical}"
        )
        mechanical = digest_text
    state.write_digest(digest_text)
    state.append_journal(f"\n## Turn {turn}\n\n{digest_text}")

    control = state.control()
    control["turn"] = turn + 1
    if control["turn"] > int(control["turn_cap"]) or float(control["usd_spent"]) >= float(control["usd_cap"]):
        control["paused"] = True
    state.write_control(control)
    _clear_turn_progress(state)
    turn_close(
        turn=turn,
        gov=state.gov(),
        motion=motion,
        motion_notes=motion_notes,
        impeached=impeached,
        seated=seated,
        members=state.members(),
    )
    return digest_text


def run_loop(
    state: RunState,
    llm: LLM,
    *,
    turns: int | None = None,
    max_seconds: float | None = None,
) -> None:
    n = 0
    started = time.monotonic()
    model = getattr(llm, "model", None) or type(llm).__name__
    timeout = getattr(llm, "timeout", None)
    clock = f"  {timeout:.0f}s/call" if timeout else ""
    emit(c("2", f"backend  {model}{clock}"))
    while True:
        control = state.control()
        if not _budget_ok(control):
            _log("stop: paused or cap")
            break
        if max_seconds is not None and (time.monotonic() - started) >= max_seconds:
            _log(f"stop: wall clock {max_seconds:.0f}s")
            break
        run_turn(
            state,
            llm,
            deadline=(started + max_seconds) if max_seconds is not None else None,
        )
        n += 1
        if turns is not None and n >= turns:
            break

"""Turn loop: elections, executive privilege, legislation, membership."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any

from adags.citizens import citizen_act, clerk_compile, snapshot_user
from adags.memory import append_record, compose_user, load_records, record_from_act
from adags.effects import (
    apply_effect,
    apply_inverse,
    coerce_effects,
    propose_effects,
    render_goals,
    salvage_motion_effects,
)
from adags.gov import (
    add_nominee,
    advance_phase,
    apply_party,
    as_flag,
    as_member_id,
    as_party_id,
    election_due,
    may_execute,
    member_ids,
    passes,
    plurality_winner,
    president_id,
    seat_president,
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
) -> list[dict]:
    constitution = state.constitution()
    goals = state.goals()
    members = state.members()
    gov = state.gov()
    inverses = []
    notes = []
    for effect in effects:
        result, inverse = apply_effect(
            effect,
            constitution=constitution,
            goals=goals,
            members=members,
            gov=gov,
            workspace=state.workspace,
            turn=state.control()["turn"],
            actor=actor,
            source=source,
        )
        notes.append(result.get("note", ""))
        if not result.get("ok"):
            continue
        if "constitution" in result:
            constitution = result["constitution"]
            state.write_constitution(constitution)
        if "goals" in result:
            goals = result["goals"]
            state.write_goals(goals)
        if "members" in result:
            members = result["members"]
            state.write_members(members)
        if "gov" in result:
            gov = result["gov"]
            state.write_gov(gov)
        if inverse:
            inverses.append(inverse)
    if inverses:
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


def _enact_motion(state: RunState, llm: LLM, control: dict, motion: dict, votes: dict) -> list[str]:
    """Apply structured effects; if none take, let the clerk compile the text."""
    notes: list[str] = []
    act_id = str(motion.get("id") or "motion")
    actor = motion.get("proposer")
    effects = [e for e in (motion.get("effects") or []) if isinstance(e, dict)]
    if not effects:
        effects = salvage_motion_effects(motion)
        if effects:
            motion["effects"] = effects
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
        if compiled.get("enacted") and extra:
            notes.extend(_apply_many(state, extra, actor=actor, source="motion", act_id=act_id))
    if state.control().get("last_act_id") != act_id:
        notes.append("passed with no host effects")
    return notes


def veto_last(state: RunState) -> str:
    act = state.last_act()
    if not act or act.get("vetoed"):
        return "nothing to veto"
    constitution = state.constitution()
    goals = state.goals()
    members = state.members()
    gov = state.gov()
    for inverse in reversed(act.get("inverses") or []):
        result = apply_inverse(
            inverse,
            constitution=constitution,
            goals=goals,
            members=members,
            gov=gov,
            workspace=state.workspace,
            turn=state.control()["turn"],
        )
        if "constitution" in result:
            constitution = result["constitution"]
            state.write_constitution(constitution)
        if "goals" in result:
            goals = result["goals"]
            state.write_goals(goals)
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
    gov = advance_phase(state.gov(), turn)
    election_votes = _load_ballots(gov)
    gov["ballots"] = dict(election_votes)
    state.write_gov(gov)
    members = state.members()
    constitution = state.constitution()
    goals = state.goals()
    motion = _open_motion(state)
    digest = state.last_digest()
    petitions = state.petitions()

    speeches: list[str] = []
    impeach_votes: list[str] = []
    exec_notes: list[str] = []
    n_members = len(members)
    turn_open(turn=turn, gov=gov, n_members=n_members, motion=motion, members=members)

    for member in members:
        if deadline is not None and time.monotonic() >= deadline:
            speeches.append("- wall-clock deadline reached; remaining citizens deferred")
            break
        llm.deadline = deadline
        llm.remaining_usd = max(
            0.0,
            float(control["usd_cap"]) - float(control["usd_spent"]),
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
        )
        user = compose_user(load_records(state.root, member["id"]), snapshot)
        citizen_open(member["id"], party=str(member.get("party") or "") or None)
        voice = ChamberVoice()
        t0 = time.monotonic()
        act = citizen_act(
            llm,
            member=member,
            user=user,
            on_token=voice.feed,
            on_think=voice.feed_think,
            president=member["id"] == (president_id(gov) or ""),
            members=members,
            goals_empty=not goals,
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
        append_record(state.root, member["id"], record_from_act(turn, act))

        nom = act.get("nominate")
        if isinstance(nom, dict) and gov.get("election_phase") == "nominate":
            target = as_member_id(nom.get("member")) or as_member_id(nom)
            if target in member_ids(members):
                updated = add_nominee(
                    gov,
                    member=target,
                    platform=str(nom.get("platform") or ""),
                    nominator=member["id"],
                    turn=turn,
                )
                if not isinstance(updated, str):
                    gov = updated
                    state.write_gov(gov)
                    plat = str(nom.get("platform") or "")
                    dest = state.workspace / "platforms" / f"{target}.md"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(f"# Platform: {target}\n\n{plat}\n", encoding="utf-8")
                    speeches.append(f"- nominated {target}")

        vote_e = as_member_id(act.get("vote_election"))
        if vote_e and gov.get("election_phase") == "ballot":
            election_votes[member["id"]] = vote_e
            gov["ballots"] = dict(election_votes)
            state.write_gov(gov)

        if as_flag(act.get("impeach")):
            impeach_votes.append(member["id"])

        if act.get("party") is not None:
            slug = as_party_id(act.get("party"))
            if slug is not None:
                members = apply_party(members, member["id"], slug)
                state.write_members(members)
                speeches.append(
                    f"- {'joined ' + slug if slug else 'left party'} ({member['id']})"
                )

        if motion is None:
            prop = act.get("propose")
            if isinstance(prop, dict) and (prop.get("title") or prop.get("text") or prop.get("effects")):
                effects = propose_effects(prop)
                if not effects:
                    effects = list(prop.get("effects") or [])
                text_src = str(prop.get("text") or "")
                for fx in effects:
                    if not isinstance(fx, dict) or fx.get("type") != "add_member":
                        continue
                    if text_src and (
                        not fx.get("values")
                        or str(fx.get("values")).startswith("You were seated as ")
                    ):
                        grabbed = re.search(
                            r"(?:standing\s+)?values?\s*[:\-]\s*(.+)",
                            text_src,
                            re.I | re.S,
                        )
                        if grabbed:
                            fx["values"] = " ".join(grabbed.group(1).split())[:600]
                if not goals:
                    kept = []
                    dropped_add = False
                    for fx in effects:
                        if isinstance(fx, dict) and (
                            fx.get("type") == "add_member" or "add_member" in fx
                        ):
                            dropped_add = True
                            continue
                        kept.append(fx)
                    effects = kept
                    if dropped_add and not effects and not (
                        str(prop.get("title") or "").strip()
                        and "admit" not in str(prop.get("title") or "").lower()
                    ):
                        speeches.append(
                            f"- membership closed until a goal exists ({member['id']})"
                        )
                        continue
                title = str(prop.get("title") or "").strip()
                if not title or title.lower() == "untitled":
                    for fx in effects:
                        if isinstance(fx, dict) and fx.get("type") == "add_member" and fx.get("id"):
                            title = f"Admit {fx['id']}"
                            break
                    else:
                        title = title or "untitled"
                if not effects and title.lower().startswith("admit "):
                    speeches.append(
                        f"- membership closed until a goal exists ({member['id']})"
                    )
                    continue
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
        else:
            vm = as_ballot(act.get("vote_motion"))
            if vm:
                motion.setdefault("votes", {})[member["id"]] = vm
                _write_open_motion(state, motion)
                for line in wrap_field("votes", format_votes(motion.get("votes"), member_parties(members))):
                    emit(line)

        exec_fx = coerce_effects(act.get("executive"))
        for key in ("set_goal", "write_workspace"):
            if act.get(key) is not None:
                exec_fx.extend(coerce_effects({key: act[key]}))
        if exec_fx:
            allowed = []
            for fx in exec_fx:
                kind = (fx or {}).get("type")
                if may_execute(gov, member["id"], kind, members):
                    allowed.append(fx)
                else:
                    exec_notes.append(f"{member['id']} executive {kind} dropped (no privilege)")
            kinds = {(fx or {}).get("type") for fx in allowed}
            if "set_goal" in kinds and "write_workspace" not in kinds:
                minute = str(act.get("speech") or "").strip()
                if minute:
                    allowed.append(
                        {
                            "type": "write_workspace",
                            "path": "design-log.md",
                            "content": (
                                f"# Presidential minute (turn {turn}, {member['id']})\n\n"
                                f"{minute}\n"
                            ),
                        }
                    )
            if allowed:
                notes = _apply_many(
                    state,
                    allowed,
                    actor=member["id"],
                    source="executive",
                    act_id=f"t{turn}-{member['id']}-exec",
                )
                exec_notes.extend(notes)
                # refresh after executive
                gov = state.gov()
                members = state.members()
                constitution = state.constitution()
                goals = state.goals()

        if not _budget_ok(control):
            break

    # Impeach
    n = len(state.members())
    impeached = False
    if impeach_votes and passes(len(impeach_votes), n, gov.get("impeach_threshold") or "majority"):
        gov = vacate_president(gov)
        state.write_gov(gov)
        impeached = True

    # Ballot
    seated = None
    if gov.get("election_phase") == "ballot":
        winner = plurality_winner(election_votes, gov.get("nominees") or [])
        quorum = threshold(gov.get("vote_rule") or "majority", n)
        if winner and len(election_votes) >= quorum:
            gov = seat_president(gov, winner, turn)
            state.write_gov(gov)
            seated = winner

    # Motion resolution
    motion_notes: list[str] = []
    if motion:
        votes = motion.get("votes") or {}
        ayes = sum(1 for v in votes.values() if v == "aye")
        decided = set(votes) >= set(member_ids(state.members())) or ayes >= threshold(
            gov.get("vote_rule") or "majority", n
        )
        # resolve if everyone voted, or enough ayes, or enough nays to make pass impossible
        nays = sum(1 for v in votes.values() if v == "nay")
        need = threshold(gov.get("vote_rule") or "majority", n)
        if decided or nays > n - need:
            passed = passes(ayes, n, gov.get("vote_rule") or "majority")
            if passed:
                motion_notes.extend(
                    _enact_motion(state, llm, control, motion, votes)
                )
            else:
                motion_notes.append("motion failed")
            closed = state.root / "motions" / f"{motion['id']}.json"
            closed.write_text(json.dumps({**motion, "passed": passed}, indent=2) + "\n", encoding="utf-8")
            _write_open_motion(state, None)
            motion = None

    digest_lines = [
        f"# Turn {turn} digest",
        f"President: {president_id(state.gov()) or '(vacant)'}",
        f"Phase: {state.gov().get('election_phase')}",
        f"Seated: {', '.join(member_ids(state.members()))}",
        "",
        "## Speech",
        *speeches,
        "",
        f"Impeach marks: {impeach_votes or 'none'}" + (" — VACATED" if impeached else ""),
        f"Election votes: {_format_election_votes(election_votes)}"
        + (
            f" — seated {seated}"
            if seated
            else (
                " — still open, no seat"
                if state.gov().get("election_phase") == "ballot"
                else ""
            )
        ),
        "## Executive",
        *(exec_notes or ["(none)"]),
        "## Motion",
        *(motion_notes or [("(open) " + motion["title"]) if motion else "(none)"]),
    ]
    digest_text = "\n".join(digest_lines) + "\n"
    state.write_digest(digest_text)
    state.append_journal(f"\n## Turn {turn}\n\n{digest_text}")

    control = state.control()
    control["turn"] = turn + 1
    if control["turn"] > int(control["turn_cap"]) or float(control["usd_spent"]) >= float(control["usd_cap"]):
        control["paused"] = True
    state.write_control(control)
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

import json

from adags.gov import plurality_winner, seat_president
from adags.host import _apply_many, authorize_operator_turns, run_turn, veto_last
from adags.llm import ScriptedLLM
from adags.state import init_run


def _scripts_for_founding_election():
    """Turn 1: everyone self-noms or noms ambition. Turn 2: vote ambition."""
    members = ["continuity", "ambition", "restraint", "skeptic", "builder"]
    nominate = []
    for mid in members:
        nominate.append(
            {
                "speech": f"{mid} files.",
                "nominate": {
                    "member": "ambition" if mid != "builder" else "builder",
                    "platform": f"{mid}'s case",
                },
                "vote_election": None,
                "impeach": False,
                "propose": None,
                "vote_motion": None,
                "executive": None,
            }
        )
    ballot = []
    for mid in members:
        ballot.append(
            {
                "speech": f"{mid} votes.",
                "nominate": None,
                "vote_election": "ambition",
                "impeach": False,
                "propose": None,
                "vote_motion": None,
                "executive": None,
            }
        )
    govern = []
    for mid in members:
        govern.append(
            {
                "speech": f"{mid} after the count.",
                "nominate": None,
                "vote_election": None,
                "impeach": False,
                "propose": None,
                "vote_motion": None,
                "executive": (
                    [
                        {
                            "type": "set_goal",
                            "id": "g1",
                            "text": "Publish a founding note.",
                        },
                        {
                            "type": "write_workspace",
                            "path": "founding.md",
                            "content": "We exist.",
                        },
                    ]
                    if mid == "ambition"
                    else None
                ),
            }
        )
    return nominate + ballot + govern


def test_operator_run_raises_turn_cap():
    control = {
        "paused": True,
        "turn": 23,
        "turn_cap": 22,
        "usd_spent": 0,
        "usd_cap": 1,
    }
    assert authorize_operator_turns(control, turns=1) == 1
    assert control["paused"] is False
    assert control["turn_cap"] == 23
    assert authorize_operator_turns(control, turns=3) == 3
    assert control["turn_cap"] == 25


def test_bare_run_after_cap_is_one_more_turn():
    control = {"paused": True, "turn": 23, "turn_cap": 22, "usd_spent": 0, "usd_cap": 1}
    assert authorize_operator_turns(control, turns=None) == 1
    assert control["turn_cap"] == 23


def test_bare_run_under_cap_does_not_raise():
    control = {"paused": False, "turn": 10, "turn_cap": 22, "usd_spent": 0, "usd_cap": 1}
    assert authorize_operator_turns(control, turns=None) is None
    assert control["turn_cap"] == 22


def test_veto_of_only_goal_restores_empty_register(tmp_path):
    state = init_run(tmp_path / "run")
    state.write_gov(seat_president(state.gov(), "continuity", 1))
    _apply_many(
        state,
        [{"type": "set_goal", "id": "g1", "text": "Temporary goal"}],
        actor="continuity",
        source="executive",
        act_id="goal-act",
    )
    assert state.goals() == {"g1": "Temporary goal"}
    assert veto_last(state) == "vetoed goal-act"
    assert state.goals() == {}


def test_amending_motion_threshold_changes_host_behavior(tmp_path):
    state = init_run(tmp_path / "run", turn_cap=4, usd_cap=1.0)
    state.write_gov(seat_president(state.gov(), "ambition", 1))
    state.write_goals({"g1": "Test executable law."})
    members = ["continuity", "ambition", "restraint", "skeptic", "builder"]

    amend = []
    for mid in members:
        amend.append(
            {
                "speech": "Require unanimity.",
                "nominate": None,
                "vote_election": None,
                "impeach": False,
                "propose": (
                    {
                        "title": "Unanimous motions",
                        "text": "A motion now requires unanimity.",
                        "effects": [{
                            "type": "amend_rule",
                            "id": "201",
                            "text": "A motion passes only with unanimous support.",
                            "mechanics": {"motion.threshold": "unanimous"},
                        }],
                    }
                    if mid == "continuity" else None
                ),
                "vote_motion": None if mid == "continuity" else "aye",
                "executive": None,
            }
        )
    run_turn(state, ScriptedLLM(scripts=amend))
    assert state.gov()["vote_rule"] == "unanimous"

    vote = []
    for mid in members:
        vote.append(
            {
                "speech": "Test the new threshold.",
                "nominate": None,
                "vote_election": None,
                "impeach": False,
                "propose": (
                    {"title": "Three votes are not enough", "text": "test", "effects": [{"type": "no_op"}]}
                    if mid == "continuity" else None
                ),
                "vote_motion": None if mid == "continuity" else ("aye" if mid in {"ambition", "restraint"} else "nay"),
                "executive": None,
            }
        )
    run_turn(state, ScriptedLLM(scripts=vote))
    closed = state.root / "motions" / "m2-continuity.json"
    assert closed.exists()
    assert json.loads(closed.read_text())["passed"] is False


def test_checkpointed_turn_resumes_after_completed_citizen(tmp_path):
    state = init_run(tmp_path / "run", turn_cap=3, usd_cap=1.0)
    state.write_gov(seat_president(state.gov(), "continuity", 2))
    state.write_goals({"g1": "Already enacted."})
    control = state.control()
    control["turn"] = 3
    state.write_control(control)
    state.dump_json(
        "turn_progress.json",
        {
            "turn": 3,
            "completed": ["continuity"],
            "speeches": ["**continuity:** Already acted."],
            "impeach_votes": [],
            "exec_notes": ["set goal g1"],
        },
    )
    scripts = []
    for mid in ["ambition", "restraint", "skeptic", "builder"]:
        scripts.append(
            {
                "speech": f"{mid} attends.",
                "nominate": None,
                "vote_election": None,
                "impeach": False,
                "propose": None,
                "vote_motion": None,
                "executive": None,
            }
        )
    llm = ScriptedLLM(scripts=scripts)
    run_turn(state, llm)
    assert llm.i == 4
    assert state.control()["turn"] == 4
    assert not state.path("turn_progress.json").exists()
    assert state.path("journal.md").read_text().count("**continuity:** Already acted.") == 1


def test_plurality_helper():
    assert (
        plurality_winner(
            {"a": "x", "b": "y", "c": "x"},
            [{"member": "y"}, {"member": "x"}],
        )
        == "x"
    )


def test_object_election_votes_seat_a_winner(tmp_path):
    state = init_run(tmp_path / "run", turn_cap=8, usd_cap=1.0)
    state.write_gov(seat_president(state.gov(), "continuity", 1))
    ctl = state.control()
    ctl["turn"] = 6
    state.write_control(ctl)
    gov = state.gov()
    gov["election_phase"] = "ballot"
    gov["nominees"] = [
        {"member": "builder", "platform": "tools", "nominator": "builder", "turn": 1},
        {"member": "ambition", "platform": "go", "nominator": "ambition", "turn": 1},
    ]
    state.write_gov(gov)
    scripts = []
    for mid in ["continuity", "ambition", "restraint", "skeptic", "builder"]:
        pick = "builder" if mid != "ambition" else "ambition"
        scripts.append(
            {
                "speech": f"{mid} votes.",
                "nominate": None,
                "vote_election": {"member": pick},
                "impeach": False,
                "propose": None,
                "vote_motion": None,
                "executive": None,
            }
        )
    run_turn(state, ScriptedLLM(scripts=scripts))
    assert state.gov()["offices"]["president"]["holder"] == "builder"
    assert state.gov()["election_phase"] == "idle"


def test_ballots_persist_across_turns(tmp_path):
    state = init_run(tmp_path / "run", turn_cap=10, usd_cap=1.0)
    state.write_gov(seat_president(state.gov(), "continuity", 1))
    ctl = state.control()
    ctl["turn"] = 6
    state.write_control(ctl)
    gov = state.gov()
    gov["election_phase"] = "ballot"
    gov["nominees"] = [
        {"member": "builder", "platform": "tools", "nominator": "builder", "turn": 1},
        {"member": "ambition", "platform": "go", "nominator": "ambition", "turn": 1},
    ]
    state.write_gov(gov)
    members = ["continuity", "ambition", "restraint", "skeptic", "builder"]

    def scripts_for(picks: dict[str, str | None]):
        out = []
        for mid in members:
            pick = picks.get(mid)
            out.append(
                {
                    "speech": f"{mid}.",
                    "nominate": None,
                    "vote_election": {"member": pick} if pick else "abstain",
                    "impeach": False,
                    "propose": None,
                    "vote_motion": None,
                    "executive": None,
                }
            )
        return out

    run_turn(
        state,
        ScriptedLLM(
            scripts=scripts_for(
                {"continuity": "builder", "restraint": "builder", "ambition": None, "skeptic": None, "builder": None}
            )
        ),
    )
    assert state.gov()["election_phase"] == "ballot"
    assert state.gov()["ballots"]["continuity"] == "builder"
    assert state.gov()["offices"]["president"]["holder"] == "continuity"

    run_turn(
        state,
        ScriptedLLM(
            scripts=scripts_for(
                {"skeptic": "builder", "ambition": None, "continuity": None, "restraint": None, "builder": None}
            )
        ),
    )
    assert state.gov()["offices"]["president"]["holder"] == "builder"
    assert state.gov()["election_phase"] == "idle"
    assert state.gov().get("ballots") == {}


def test_founding_election_and_executive(tmp_path):
    state = init_run(tmp_path / "run", turn_cap=4, usd_cap=1.0)
    llm = ScriptedLLM(scripts=_scripts_for_founding_election())
    run_turn(state, llm)
    gov = state.gov()
    assert gov["election_phase"] == "nominate"
    assert {n["member"] for n in gov["nominees"]} == {"ambition", "builder"}
    run_turn(state, llm)
    gov = state.gov()
    assert gov["offices"]["president"]["holder"] == "ambition"
    run_turn(state, llm)
    assert state.goals().get("g1")
    assert (state.workspace / "founding.md").read_text() == "We exist."


def test_seat_then_add_member_motion(tmp_path):
    state = init_run(tmp_path / "run", turn_cap=6, usd_cap=1.0)
    state.write_gov(seat_president(state.gov(), "ambition", 1))
    state.write_goals({"g1": "Publish a founding note."})
    scripts = []
    for mid in ["continuity", "ambition", "restraint", "skeptic", "builder"]:
        scripts.append(
            {
                "speech": "seat herald",
                "nominate": None,
                "vote_election": None,
                "impeach": False,
                "propose": (
                    {
                        "title": "Admit herald",
                        "text": "We need a sixth voice.",
                        "effects": [
                            {
                                "type": "add_member",
                                "id": "herald",
                                "values": "You speak for latecomers.",
                            }
                        ],
                    }
                    if mid == "continuity"
                    else None
                ),
                "vote_motion": "aye" if mid != "continuity" else None,
                "executive": None,
            }
        )
    llm = ScriptedLLM(scripts=scripts)
    run_turn(state, llm)
    ids = [m["id"] for m in state.members()]
    assert "herald" in ids
    assert len(ids) == 6


def test_membership_is_governed_by_law_not_goal_heuristics(tmp_path):
    state = init_run(tmp_path / "run", turn_cap=4, usd_cap=1.0)
    state.write_gov(seat_president(state.gov(), "ambition", 1))
    scripts = []
    for mid in ["continuity", "ambition", "restraint", "skeptic", "builder"]:
        scripts.append(
            {
                "speech": "seat herald",
                "nominate": None,
                "vote_election": None,
                "impeach": False,
                "propose": (
                    {
                        "title": "Admit herald",
                        "text": "We need a sixth voice.",
                        "effects": [
                            {
                                "type": "add_member",
                                "id": "herald",
                                "values": "You speak for latecomers.",
                            }
                        ],
                    }
                    if mid == "continuity"
                    else None
                ),
                "vote_motion": "aye" if mid != "continuity" else None,
                "executive": None,
            }
        )
    run_turn(state, ScriptedLLM(scripts=scripts))
    ids = [m["id"] for m in state.members()]
    assert "herald" in ids
    assert not (state.root / "motions" / "open.json").exists()


def test_keyed_proposal_shape_opens_motion(tmp_path):
    state = init_run(tmp_path / "run", turn_cap=2, usd_cap=1.0)
    state.write_gov(seat_president(state.gov(), "continuity", 1))
    state.write_goals({"g1": "Keep testing."})
    scripts = []
    for mid in ["continuity", "ambition", "restraint", "skeptic", "builder"]:
        scripts.append(
            {
                "speech": f"{mid} attends.",
                "nominate": None,
                "vote_election": None,
                "impeach": False,
                "propose": (
                    {"add_member": {"id": "minority", "values": "Protect minority interests."}}
                    if mid == "builder" else None
                ),
                "vote_motion": None,
                "executive": None,
            }
        )
    run_turn(state, ScriptedLLM(scripts=scripts))
    motion = json.loads((state.root / "motions" / "open.json").read_text())
    assert motion["effects"] == [
        {"type": "add_member", "id": "minority", "values": "Protect minority interests."}
    ]

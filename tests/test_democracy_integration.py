import tempfile
from pathlib import Path

from adags.state import init_run
from adags.host import run_turn
from adags.llm import ScriptedLLM
from adags.gov import seat_president


def _act(mid, **over):
    base = {"speech": f"{mid} speaks.", "vote_motion": None, "propose": None, "question": None, "executive": None}
    base.update(over)
    return base


def test_committee_motion_full_pipeline(tmp_path):
    root = tmp_path / "run"
    state = init_run(root, found=7)
    gov = seat_president(state.gov(), "continuity", 1)
    state.write_gov(gov)

    scripts = []
    for m in state.members():
        mid = m["id"]
        if mid == "continuity":
            scripts.append(_act(
                mid,
                speech="Motion to form the works committee.",
                propose={"type": "appoint", "committee": "works",
                         "members": ["continuity", "skeptic"], "chair": "continuity"},
            ))
        else:
            scripts.append(_act(mid, vote_motion="aye"))
    run_turn(state, ScriptedLLM(scripts=scripts))  # opens motion
    scripts2 = [_act(m["id"], vote_motion="aye") for m in state.members()]
    run_turn(state, ScriptedLLM(scripts=scripts2))  # resolves it

    cf = root / "committees.json"
    assert cf.exists(), "committee should be formed after motion passes"
    data = __import__("json").loads(cf.read_text())
    assert data["works"]["chair"] == "continuity"

    # jurisdiction enforced: skeptic (member) may write, outsider may not
    from adags import committees as cm
    assert cm.gate_write(root, "works/plan.md", "skeptic", president="continuity") is None
    assert cm.gate_write(root, "works/plan.md", "builder", president=None) is not None


def test_question_flows_through_turn(tmp_path):
    root = tmp_path / "run"
    state = init_run(root, found=7)
    gov = seat_president(state.gov(), "continuity", 1)
    state.write_gov(gov)
    scripts = [
        _act("continuity", question={"to": "skeptic", "body": "where is your file?"}),
        *[_act(m["id"]) for m in state.members()[1:]],
    ]
    run_turn(state, ScriptedLLM(scripts=scripts))
    dig = (root / "digest.md").read_text()
    assert any(l.startswith("Questions:") and "skeptic" in l for l in dig.splitlines())


def test_term_record_opens_through_natural_election(tmp_path):
    root = tmp_path / "run"
    state = init_run(root, found=7)
    # vacant presidency: turn 1 nominates, turn 2 ballots and seats
    scripts1 = []
    first = state.members()[0]["id"]
    for i, m in enumerate(state.members()):
        if i == 0:
            scripts1.append({
                "speech": "I will produce works/bridge.md naming goal1.",
                "nominate": {"member": m["id"], "platform": "I will produce works/bridge.md naming goal1"},
            })
        else:
            scripts1.append(_act(m["id"]))
    run_turn(state, ScriptedLLM(scripts=scripts1))
    scripts2 = [
        {"speech": "voting", "vote_election": first} for _ in state.members()
    ]
    run_turn(state, ScriptedLLM(scripts=scripts2))
    tf = root / "terms.json"
    assert tf.exists(), "term record should open when a president is seated"
    data = __import__("json").loads(tf.read_text())
    assert any(t["holder"] == first and not t["closed"] for t in data)
    assert data[-1]["platform"], "winner's platform should be on record"

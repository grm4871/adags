import json

from adags import committees as committees_mod
from adags import questions as questions_mod
from adags import terms as terms_mod
from adags.opposition import opposition_card, opposition_id
from adags.seed import default_gov
from adags.treasury import init


def _members(*pairs):
    return [{"id": mid, "party": party} for mid, party in pairs]


# --- Committees ---

def test_committee_create_and_gate(tmp_path):
    root = tmp_path
    err = committees_mod.create(
        root, name="Budget", members=["warden", "broker"], chair="warden"
    )
    assert err is None
    # member may write under jurisdiction; outsider may not
    assert committees_mod.gate_write(root, "budget/plan.md", "warden", None) is None
    assert committees_mod.gate_write(root, "budget/plan.md", "broker", None) is None
    refusal = committees_mod.gate_write(root, "budget/plan.md", "skeptic", None)
    assert refusal and "budget" in refusal
    # outside any committee prefix: unaffected
    assert committees_mod.gate_write(root, "notes.md", "skeptic", None) is None
    # chair always allowed even if roster edited away
    assert committees_mod.gate_write(root, "budget/x.md", "warden", "someone_else") is None


def test_committee_membership_card(tmp_path):
    root = tmp_path
    committees_mod.create(root, name="audit", members=["a", "b"], chair="a")
    mine = committees_mod.memberships_for(root, "b")
    assert mine == [{"name": "audit", "chair": False}]
    card = committees_mod.committee_card(root)
    assert "audit" in card and "chair" in card


def test_committee_dissolve_and_create_validation(tmp_path):
    root = tmp_path
    assert committees_mod.create(root, name="", members=["a"]) is not None
    assert committees_mod.create(root, name="x", members=[]) is not None
    committees_mod.create(root, name="temp", members=["a"])
    assert committees_mod.dissolve(root, name="temp")
    assert not committees_mod.dissolve(root, name="temp")


def test_appoint_effect_forms_committee(tmp_path):
    from adags.effects import apply_effect

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    members = [{"id": m} for m in ("a", "b")]
    result, inverse = apply_effect(
        {"type": "appoint", "committee": "roads", "members": ["a", "ghost"], "chair": "a"},
        law={}, goals={}, members=members, gov={},
        workspace=workspace, turn=1, actor="a", source="motion",
    )
    assert result["ok"], result
    data = json.loads((tmp_path / "committees.json").read_text())
    assert data["roads"]["members"] == ["a"]  # ghost filtered (not seated)


# --- Questions ---

def test_question_parse_and_routing():
    seated = ["a", "b"]
    ok = questions_mod.parse_question(
        {"to": "b", "body": "where is the file?"}, sender="a", seated=seated
    )
    assert ok == {"from": "a", "to": "b", "body": "where is the file?"}
    # string shorthand
    ok2 = questions_mod.parse_question("b: why no budget?", sender="a", seated=seated)
    assert ok2["body"] == "why no budget?"
    assert isinstance(
        questions_mod.parse_question({"to": "b"}, sender="a", seated=seated), str
    )
    assert isinstance(
        questions_mod.parse_question({"to": "a", "body": "self"}, sender="a", seated=seated), str
    )
    assert questions_mod.parse_question(None, sender="a", seated=seated) is None


def test_question_inbox_roundtrip(tmp_path):
    root = tmp_path
    questions_mod.save_hold(root, {"b": [{"from": "a", "to": "b", "body": "q"}]})
    inbox = questions_mod.load_hold(root)
    text = questions_mod.format_inbox(inbox["b"])
    assert "From a" in text and "public record" in text.lower() or "Answer" in text


# --- Terms ---

def test_term_lifecycle_scores_platform(tmp_path):
    root = tmp_path
    terms_mod.open_term(root, holder="a", turn=2, platform="I will build the bridge")
    terms_mod.add_promise(root, holder="a", text="bridge plans")
    terms_mod.add_promise(root, holder="a", text="toll schedule")
    terms_mod.mark_delivered(root, holder="a", rel_path="plans.md")
    closed = terms_mod.close_term(root, turn=10)
    assert closed["holder"] == "a" and closed["score"] == "1/2"
    card = terms_mod.card(root)
    assert "scored 1/2" in card and "bridge" in card


def test_close_term_without_open_is_noop(tmp_path):
    root = tmp_path
    assert terms_mod.close_term(root, turn=5) is None


# --- Opposition ---

def test_opposition_requires_a_real_caucus():
    gov = default_gov()
    gov["offices"]["president"]["holder"] = "prez"
    # lone critic is not an opposition
    members = _members(("prez", ""), ("solo", "minority"))
    assert opposition_id(members, gov) is None
    # a two-member caucus excluding the president is recognized
    members = _members(("prez", "ruling"), ("a", "opp"), ("b", "opp"))
    assert opposition_id(members, gov) == "a"
    # largest caucus wins; president's own caucus excluded
    members = _members(("prez", "big"), ("a", "small"), ("b", "small"), ("c", "big"))
    assert opposition_id(members, gov) == "a"


def test_opposition_card_targets_the_right_reader():
    gov = default_gov()
    gov["offices"]["president"]["holder"] = "prez"
    members = _members(("prez", "ruling"), ("a", "opp"), ("b", "opp"), ("c", ""))
    leader_card = opposition_card(members, gov, member_id="a")
    assert "Leader of the Opposition" in leader_card and "You are recognized" in leader_card
    prez_card = opposition_card(members, gov, member_id="prez")
    assert "Expect their questions" in prez_card
    other_card = opposition_card(members, gov, member_id="c")
    assert "Leader of the Opposition: a" in other_card


# --- Treasury dividend + marginal math ---

def test_dividend_makes_completed_goals_sustainable(tmp_path):
    from adags.treasury import settle, load
    from adags.constitution import default_constitution

    law = default_constitution()
    law["rules"]["213"]["mechanics"].update(
        {"economy.member_upkeep": 3, "economy.complete_dividend": 1}
    )
    init(root := tmp_path, law=law)
    clock = "goal1 complete 2/2 files"
    settle(root, law=law, turn=1, n_members=2, goals={"goal1": "x"}, goal_clock_text=clock)
    after_yield = load(root)["credits"]
    settle(root, law=law, turn=2, n_members=2, goals={"goal1": "x"}, goal_clock_text=clock)
    steady = load(root)["credits"]
    assert steady - after_yield == -6 + 1  # upkeep x2 minus dividend x1

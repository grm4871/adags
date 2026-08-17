from pathlib import Path

from adags.effects import apply_effect
from adags.seed import CONSTITUTION, FOUNDING_MEMBERS, default_gov


def _apply(effect, tmp_path: Path, *, gov=None, members=None, actor="ambition", source="motion"):
    gov = gov if gov is not None else default_gov()
    members = members if members is not None else list(FOUNDING_MEMBERS)
    return apply_effect(
        effect,
        constitution=CONSTITUTION,
        goals={},
        members=members,
        gov=gov,
        workspace=tmp_path,
        turn=1,
        actor=actor,
        source=source,
    )


def test_cannot_amend_100_series(tmp_path):
    r, inv = _apply({"type": "amend_rule", "id": "103", "text": "no veto"}, tmp_path)
    assert not r["ok"]
    assert inv is None


def test_coerce_nested_executive_shapes(tmp_path):
    from adags.effects import coerce_effects
    from adags.gov import seat_president

    gov = seat_president(default_gov(), "ambition", 1)
    r, _ = _apply(
        {"write_workspace": "# Design log\nWe exist."},
        tmp_path,
        gov=gov,
        actor="ambition",
        source="executive",
    )
    assert r["ok"], r
    assert (tmp_path / "design-log.md").read_text().startswith("# Design log")
    r, _ = _apply(
        {"set_goal": {"text": "Ship a prototype by turn 8."}},
        tmp_path,
        gov=gov,
        actor="ambition",
        source="executive",
        members=list(FOUNDING_MEMBERS),
    )
    # _apply uses empty goals
    assert r["ok"], r
    assert any("Ship a prototype" in t for t in r["goals"].values())
    assert coerce_effects({"write_workspace": "hi"})[0]["path"] == "design-log.md"
    both = coerce_effects(
        {
            "set_goal": "protect minorities by turn 13",
            "write_workspace": "Minute: begin review framework.",
        }
    )
    kinds = {e["type"] for e in both}
    assert kinds == {"set_goal", "write_workspace"}
    assert both[1]["content"].startswith("Minute")
    from adags.effects import propose_effects, salvage_motion_effects

    keyed = propose_effects({"repeal_goal": "goal1", "add_member": None})
    assert keyed == [{"type": "repeal_goal", "id": "goal1"}]
    salvaged = salvage_motion_effects(
        {
            "title": "repeal_goal goal1",
            "text": "I propose repeal_goal goal1 to replace with quarterly harm audits.",
        }
    )
    assert salvaged[0]["type"] == "repeal_goal"
    assert salvaged[1]["type"] == "set_goal"
    assert "quarterly" in salvaged[1]["text"]
    r, _ = _apply(
        {"write_workspace": {"description": "Establish a shared design log."}},
        tmp_path,
        gov=gov,
        actor="ambition",
        source="executive",
    )
    assert r["ok"], r
    assert "shared design log" in (tmp_path / "design-log.md").read_text()


def test_normalize_nested_amend_rule(tmp_path):
    from adags.effects import normalize_effect

    wrapped = {
        "amend_rule": {
            "id": "208",
            "text": "Term is eight turns.",
        }
    }
    assert normalize_effect(wrapped) == {
        "type": "amend_rule",
        "id": "208",
        "text": "Term is eight turns.",
    }
    r, _ = _apply(wrapped, tmp_path)
    assert r["ok"]
    assert "Term is eight turns." in r["constitution"]


def test_nested_amend_non_numeric_adds_new_rule(tmp_path):
    r, _ = _apply(
        {
            "amend_rule": {
                "id": "executive_privileges",
                "text": "two thirds to expand.",
            }
        },
        tmp_path,
    )
    assert r["ok"]
    assert "two thirds to expand." in r["constitution"]


def test_can_amend_200_series(tmp_path):
    r, inv = _apply({"type": "amend_rule", "id": "208", "text": "Term is eight turns."}, tmp_path)
    assert r["ok"]
    assert "208. Term is eight turns." in r["constitution"]
    assert inv["type"] == "amend_rule"


def test_add_member_open(tmp_path):
    r, inv = _apply(
        {"type": "add_member", "id": "herald", "values": "Speak for latecomers."},
        tmp_path,
    )
    assert r["ok"]
    ids = [m["id"] for m in r["members"]]
    assert ids == [m["id"] for m in FOUNDING_MEMBERS] + ["herald"]
    assert inv["type"] == "remove_member"


def test_add_member_rejects_bad_id(tmp_path):
    r, _ = _apply({"type": "add_member", "id": "Bad Name"}, tmp_path)
    assert not r["ok"]


def test_add_member_respects_optional_cap(tmp_path):
    gov = default_gov()
    gov["max_members"] = 5
    r, _ = _apply({"type": "add_member", "id": "herald", "values": "x"}, tmp_path, gov=gov)
    assert not r["ok"]
    assert "max_members" in r["note"]


def test_cannot_remove_last_member(tmp_path):
    r, _ = _apply(
        {"type": "remove_member", "id": "ambition"},
        tmp_path,
        members=[{"id": "ambition", "values": "x"}],
    )
    assert not r["ok"]


def test_set_goal_executive_is_president_only(tmp_path):
    gov = default_gov()
    gov["offices"]["president"]["holder"] = "ambition"
    r, _ = _apply(
        {"type": "set_goal", "id": "g1", "text": "Write a charter."},
        tmp_path,
        gov=gov,
        actor="skeptic",
        source="executive",
    )
    assert not r["ok"]
    r, _ = _apply(
        {"type": "set_goal", "id": "g1", "text": "Write a charter."},
        tmp_path,
        gov=gov,
        actor="ambition",
        source="executive",
    )
    assert r["ok"]
    r, _ = _apply(
        {"type": "set_goal", "id": "g2", "text": "Floor-enacted goal."},
        tmp_path,
        gov=gov,
        actor="skeptic",
        source="motion",
    )
    assert r["ok"]
    assert r["goals"]["g2"] == "Floor-enacted goal."


def test_gov_dot_max_members_and_term_syncs_rule_208(tmp_path):
    r, _ = _apply({"type": "set_param", "key": "gov.max_members", "value": 7}, tmp_path)
    assert r["ok"], r
    assert r["gov"]["max_members"] == 7
    r, _ = _apply({"type": "set_param", "key": "term_length", "value": 3}, tmp_path)
    assert r["ok"]
    assert r["gov"]["term_length"] == 3
    assert "Term is three turns" in r["constitution"]


def test_appoint_president_inert_while_elections_on(tmp_path):
    r, _ = _apply(
        {"type": "appoint", "office": "president", "holder": "ambition"},
        tmp_path,
        source="motion",
    )
    assert not r["ok"]

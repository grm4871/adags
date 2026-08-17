from pathlib import Path

from adags.constitution import default_constitution, value
from adags.effects import apply_effect
from adags.seed import FOUNDING_MEMBERS, default_gov


def _apply(effect, tmp_path: Path, *, law=None, gov=None, members=None, actor="ambition", source="motion"):
    gov = gov if gov is not None else default_gov()
    members = members if members is not None else list(FOUNDING_MEMBERS)
    return apply_effect(
        effect,
        law=law or default_constitution(),
        goals={},
        members=members,
        gov=gov,
        workspace=tmp_path,
        turn=1,
        actor=actor,
        source=source,
    )


def test_cannot_amend_100_series(tmp_path):
    r, inv = _apply({"type": "amend_rule", "id": "103", "text": "no veto", "mechanics": {"motion.threshold": "unanimous"}}, tmp_path)
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
    from adags.effects import propose_effects

    keyed = propose_effects({"repeal_goal": "goal1", "add_member": None})
    assert keyed == [{"type": "repeal_goal", "id": "goal1"}]
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
            "mechanics": {"election.term_length": 8},
        }
    }
    assert normalize_effect(wrapped) == {
        "type": "amend_rule",
        "id": "208",
        "text": "Term is eight turns.",
        "mechanics": {"election.term_length": 8},
    }
    r, _ = _apply(wrapped, tmp_path)
    assert r["ok"]
    assert value(r["law"], "election.term_length") == 8


def test_amend_rejects_non_numeric_rule_id(tmp_path):
    r, _ = _apply(
        {
            "amend_rule": {
                "id": "executive_privileges",
                "text": "two thirds to expand.",
                "mechanics": {"motion.threshold": "two_thirds"},
            }
        },
        tmp_path,
    )
    assert not r["ok"]


def test_can_amend_200_series(tmp_path):
    r, inv = _apply({"type": "amend_rule", "id": "208", "text": "Term is eight turns.", "mechanics": {"election.term_length": 8}}, tmp_path)
    assert r["ok"]
    assert value(r["law"], "election.term_length") == 8
    assert inv["type"] == "_restore_rule"


def test_prose_only_amendment_is_not_law(tmp_path):
    r, inv = _apply({"type": "amend_rule", "id": "201", "text": "Unanimity."}, tmp_path)
    assert not r["ok"]
    assert inv is None


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
    law = default_constitution()
    law["rules"]["211"]["mechanics"]["membership.max_members"] = 5
    r, _ = _apply({"type": "add_member", "id": "herald", "values": "x"}, tmp_path, law=law)
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


def test_removing_executive_privilege_disables_effect(tmp_path):
    law = default_constitution()
    law["rules"]["207"]["mechanics"]["offices.president.privileges"] = []
    gov = default_gov()
    gov["offices"]["president"]["holder"] = "ambition"
    r, _ = _apply(
        {"type": "set_goal", "id": "g1", "text": "Must stay inert."},
        tmp_path,
        law=law,
        gov=gov,
        actor="ambition",
        source="executive",
    )
    assert not r["ok"]


def test_unsupported_mechanic_is_rejected(tmp_path):
    r, _ = _apply({"type": "amend_rule", "id": "201", "text": "Let the clerk decide.", "mechanics": {"motion.magic": True}}, tmp_path)
    assert not r["ok"]
    assert "unsupported constitutional mechanic" in r["note"]


def test_host_suggestion_is_filed_but_changes_no_law(tmp_path):
    law = default_constitution()
    r, inverse = _apply(
        {
            "type": "suggest_host_change",
            "title": "Ranked ballots",
            "text": "Please consider publishing a ranked-choice mechanic.",
        },
        tmp_path / "workspace",
        law=law,
    )
    assert r["ok"]
    files = list((tmp_path / "suggestions").glob("*.md"))
    assert len(files) == 1
    assert "pending host review" in files[0].read_text()
    assert "law" not in r
    assert inverse["type"] == "_delete_suggestion"


def test_appoint_president_inert_while_elections_on(tmp_path):
    r, _ = _apply(
        {"type": "appoint", "office": "president", "holder": "ambition"},
        tmp_path,
        source="motion",
    )
    assert not r["ok"]

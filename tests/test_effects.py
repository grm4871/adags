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
    from adags.effects import bill_title, propose_effects

    keyed = propose_effects({"repeal_goal": "goal1", "add_member": None})
    assert keyed == [{"type": "repeal_goal", "id": "goal1"}]
    bare = propose_effects(
        {
            "type": "amend_rule",
            "id": "207",
            "text": "The President alone may write the workspace and set goals.",
            "mechanics": {"offices.president.privileges": []},
        }
    )
    assert bare[0]["type"] == "amend_rule"
    assert bare[0]["id"] == "207"
    assert bare[0]["mechanics"]["offices.president.privileges"] == []
    seat = propose_effects(
        {"type": "add_member", "id": "skeptic2", "values": "A minority voice."}
    )
    assert seat == [{"type": "add_member", "id": "skeptic2", "values": "A minority voice."}]
    assert bill_title(
        title="untitled",
        text="The President alone may write the workspace and set goals as executive acts.",
        effects=bare,
    ).startswith("amend 207:")
    assert (
        bill_title(title="untitled", text="Workspace entries must cite a goal.", effects=[])
        == "Workspace entries must cite a goal"
    )
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

    aliased = normalize_effect(
        {"amend_rule": {"rule_id": 213, "new_text": "Require unanimity.", "mechanics": {"motion.threshold": "unanimous"}}}
    )
    assert aliased["id"] == "213"
    assert aliased["text"] == "Require unanimity."


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


def test_newer_rule_can_override_a_published_mechanic(tmp_path):
    from adags.constitution import value

    r, _ = _apply(
        {
            "type": "amend_rule",
            "id": "213",
            "text": "Motions require two thirds.",
            "mechanics": {"motion.threshold": "two_thirds"},
        },
        tmp_path,
    )
    assert r["ok"]
    assert value(r["law"], "motion.threshold") == "two_thirds"


def test_prose_only_host_rule_relabels_without_changing_knobs(tmp_path):
    r, inv = _apply({"type": "amend_rule", "id": "201", "text": "Unanimity is our custom."}, tmp_path)
    assert r["ok"]
    assert value(r["law"], "motion.threshold") == "majority"
    assert "Unanimity is our custom" in r["law"]["rules"]["201"]["text"]
    assert inv["type"] == "_restore_rule"


def test_unenforceable_article_becomes_chamber_law(tmp_path):
    r, _ = _apply(
        {
            "type": "amend_rule",
            "id": "213",
            "text": "Workspace artifacts must reference an active goal.",
            "mechanics": {"workspace.require_goal": True},
        },
        tmp_path,
    )
    assert r["ok"], r
    assert "213" not in (r["law"].get("rules") or {})
    charter = r["law"]["charter"]
    assert any("active goal" in (a.get("text") or "") for a in charter.values())
    assert "chamber law" in r["note"]


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
    assert not r["ok"]
    assert "reserved to the President" in r["note"]


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
    floor, _ = _apply(
        {"type": "set_goal", "id": "g1", "text": "Now enacted by the floor."},
        tmp_path,
        law=law,
        gov=gov,
        actor="skeptic",
        source="motion",
    )
    assert floor["ok"]


def test_write_workspace_uses_named_path_not_design_log(tmp_path):
    from adags.effects import coerce_effects
    from adags.gov import seat_president

    gov = seat_president(default_gov(), "ambition", 1)
    r, _ = _apply(
        {"write_workspace": {"path": "workspace/builder-goals.md", "content": "Builder goals live here."}},
        tmp_path,
        gov=gov,
        actor="ambition",
        source="executive",
    )
    assert r["ok"], r
    assert (tmp_path / "builder-goals.md").read_text().startswith("Builder")
    assert not (tmp_path / "design-log.md").exists()
    r, _ = _apply(
        {
            "type": "write_workspace",
            "path": "workspace/participation-log.md",
            "content": "A real participation note.",
        },
        tmp_path,
        gov=gov,
        actor="ambition",
        source="executive",
    )
    assert r["ok"], r
    assert "participation" in (tmp_path / "participation-log.md").read_text()
    fx = coerce_effects({"write_workspace": {"path": "workspace/foo.md", "content": "hello"}})[0]
    assert fx["path"] == "foo.md"
    assert fx["content"] == "hello"
    nested = coerce_effects(
        {"type": "write_workspace", "path": "workspace/workspace/participation-log.md", "content": "log"}
    )[0]
    assert nested["path"] == "participation-log.md"


def test_identical_charter_text_is_already_law(tmp_path):
    from adags.constitution import identical_charter_line

    first, _ = _apply(
        {"type": "amend_rule", "id": "302", "text": "Any law that adds a duty must repeal a conflicting one."},
        tmp_path,
    )
    assert first["ok"]
    clone, _ = _apply(
        {"type": "amend_rule", "text": "Any law that adds a duty must repeal a conflicting one."},
        tmp_path,
        law=first["law"],
    )
    assert clone["ok"]
    assert "already law 302" in clone["note"]
    assert "303" not in (clone["law"].get("charter") or {})
    again, _ = _apply(
        {"type": "amend_rule", "id": "304", "text": "Any  law that   adds a duty must repeal a conflicting one."},
        tmp_path,
        law=first["law"],
    )
    assert "already law 302" in again["note"]
    assert identical_charter_line(first["law"]) == ""
    piled = dict(first["law"])
    piled["charter"] = {
        **first["law"]["charter"],
        "304": {"text": "Any law that adds a duty must repeal a conflicting one."},
    }
    assert "302 = 304" in identical_charter_line(piled)


def test_set_goal_refuses_a_fourth_slot(tmp_path):
    from adags.gov import seat_president

    gov = seat_president(default_gov(), "ambition", 1)
    law = default_constitution()
    goals = {"goal1": "a", "goal2": "b", "goal3": "c"}
    r, _ = apply_effect(
        {"type": "set_goal", "id": "goal4", "text": "one too many"},
        law=law,
        goals=goals,
        members=list(FOUNDING_MEMBERS),
        gov=gov,
        workspace=tmp_path,
        turn=1,
        actor="ambition",
        source="executive",
    )
    assert not r["ok"]
    assert "register full" in r["note"]
    replace, _ = apply_effect(
        {"type": "set_goal", "id": "goal2", "text": "replaced"},
        law=law,
        goals=goals,
        members=list(FOUNDING_MEMBERS),
        gov=gov,
        workspace=tmp_path,
        turn=1,
        actor="ambition",
        source="executive",
    )
    assert replace["ok"]
    assert replace["goals"]["goal2"] == "replaced"


def test_empty_write_is_refused(tmp_path):
    from adags.gov import seat_president

    gov = seat_president(default_gov(), "ambition", 1)
    empty, _ = _apply(
        {"type": "write_workspace", "path": "enforcement.md", "content": ""},
        tmp_path,
        gov=gov,
        actor="ambition",
        source="executive",
    )
    assert not empty["ok"]
    assert "wrote nothing" in empty["note"]
    assert not (tmp_path / "enforcement.md").exists()
    named, _ = _apply(
        {"type": "write_workspace", "path": "enforcement.md", "content": "enforcement.md"},
        tmp_path,
        gov=gov,
        actor="ambition",
        source="executive",
    )
    assert not named["ok"]


def test_set_goal_honors_goalN_ids():
    from adags.effects import coerce_effects, complete_set_goal

    labeled = coerce_effects({"set_goal": "goal3: maintain enforced chamber law"})[0]
    assert labeled["id"] == "goal3"
    assert labeled["text"].startswith("maintain")
    only = coerce_effects({"set_goal": "goal4"})[0]
    assert only["id"] == "goal4"
    assert only["text"] == ""
    filled = complete_set_goal(
        {"type": "set_goal", "text": "goal4"},
        speech="As President, I set goal4: complete the founding charter and enforce chamber law.",
    )
    assert filled["id"] == "goal4"
    assert "founding charter" in filled["text"]
    keep = coerce_effects({"type": "set_goal", "id": "g1", "text": "Write a charter."})[0]
    assert keep["id"] == "g1"
    prose = coerce_effects({"set_goal": "protect minorities by turn 13"})[0]
    assert prose["id"] == "goal1"
    assert "protect minorities" in prose["text"]


def test_write_workspace_extracts_path_from_prose():
    from adags.effects import coerce_effects, path_in_prose

    assert path_in_prose("Update founding_charter.md to reflect 303.") == "founding_charter.md"
    fx = coerce_effects(
        {
            "type": "write_workspace",
            "id": None,
            "text": "Update founding_charter.md to reflect chamber law 303.",
        }
    )[0]
    assert fx["path"] == "founding_charter.md"
    assert "303" in fx["content"]


def test_override_alias_becomes_published_207_knob(tmp_path):
    r, _ = _apply(
        {
            "type": "amend_rule",
            "id": "207",
            "text": "President exclusive unless supermajority shares access.",
            "mechanics": {
                "offices.president.privileges": ["write_workspace", "set_goal"],
                "executive.override.threshold": "supermajority",
            },
        },
        tmp_path,
    )
    assert r["ok"], r
    assert value(r["law"], "offices.president.override") == "two_thirds"
    gov = default_gov()
    gov["offices"]["president"]["holder"] = "ambition"
    floor, _ = _apply(
        {"type": "set_goal", "id": "g2", "text": "Floor goal via override."},
        tmp_path,
        law=r["law"],
        gov=gov,
        actor="skeptic",
        source="motion",
    )
    assert floor["ok"], floor


def test_unsupported_mechanic_is_rejected(tmp_path):
    r, _ = _apply({"type": "amend_rule", "id": "201", "text": "Let the clerk decide.", "mechanics": {"motion.magic": True}}, tmp_path)
    assert not r["ok"]
    assert "unsupported mechanic" in r["note"]


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

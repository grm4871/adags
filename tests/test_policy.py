from adags.effects import apply_effect, apply_inverse, coerce_effects, inert_motion_note
from adags.gov import seat_president
from adags.policy import (
    DEFAULT_POLICY,
    campaign_text,
    ensure_policy,
    load_policy,
    policy_card,
    save_policy,
)
from adags.seed import FOUNDING_MEMBERS, default_gov
from adags.constitution import default_constitution
from adags.state import init_run
from adags.citizens import snapshot_user
from adags.seed import CONSTITUTION


def test_init_run_seeds_policy(tmp_path):
    state = init_run(tmp_path / "run")
    text = (state.root / "policy.md").read_text(encoding="utf-8")
    assert "Nation policy" in text
    assert "Direction" in text


def test_only_president_may_edit_policy(tmp_path):
    gov = seat_president(default_gov(), "ambition", 1)
    law = default_constitution()
    body = DEFAULT_POLICY.replace("(none yet — first President: write the campaign you won on)", "Win office, then file proof.")
    denied, _ = apply_effect(
        {"type": "edit_policy", "body": body},
        law=law,
        goals={},
        members=list(FOUNDING_MEMBERS),
        gov=gov,
        workspace=tmp_path / "workspace",
        turn=2,
        actor="builder",
        source="executive",
    )
    assert not denied["ok"]
    (tmp_path / "workspace").mkdir()
    ensure_policy(tmp_path)
    ok, inverse = apply_effect(
        {"type": "edit_policy", "body": body},
        law=law,
        goals={},
        members=list(FOUNDING_MEMBERS),
        gov=gov,
        workspace=tmp_path / "workspace",
        turn=2,
        actor="ambition",
        source="executive",
    )
    assert ok["ok"]
    assert ok["note"] == "edited nation policy"
    assert ok["gov"]["policy_due"] is False
    assert ok["gov"]["policy_editor"] == "ambition"
    assert "Win office" in load_policy(tmp_path)
    assert inverse and inverse["type"] == "_restore_policy"


def test_successor_inherits_policy_and_veto_restores(tmp_path):
    (tmp_path / "workspace").mkdir()
    ensure_policy(tmp_path)
    first = DEFAULT_POLICY.replace("## Direction\n(none yet — first President: write the campaign you won on)", "## Direction\nCivic forums.")
    law = default_constitution()
    gov = seat_president(default_gov(), "ambition", 2)
    applied, inverse = apply_effect(
        {"edit_policy": first},
        law=law,
        goals={},
        members=list(FOUNDING_MEMBERS),
        gov=gov,
        workspace=tmp_path / "workspace",
        turn=2,
        actor="ambition",
        source="executive",
    )
    assert applied["ok"]
    later = load_policy(tmp_path)
    assert "Civic forums." in later
    gov2 = seat_president(applied["gov"], "builder", 10)
    assert gov2["policy_due"] is True
    assert "Civic forums." in load_policy(tmp_path)
    restored = apply_inverse(inverse, law=law, goals={}, members=list(FOUNDING_MEMBERS), gov=gov, workspace=tmp_path / "workspace", turn=2)
    assert restored["ok"]
    assert "Civic forums." not in load_policy(tmp_path)


def test_floor_cannot_open_an_edit_policy_motion():
    gov = seat_president(default_gov(), "ambition", 1)
    note = inert_motion_note(
        [{"type": "edit_policy", "body": DEFAULT_POLICY + "\nMore."}],
        law=default_constitution(),
        goals={},
        members=list(FOUNDING_MEMBERS),
        gov=gov,
    )
    assert note and "reserved to the President" in note


def test_policy_card_is_president_only_and_shows_campaign(tmp_path):
    gov = seat_president(default_gov(), "ambition", 2)
    gov["policy_due"] = True
    plat = tmp_path / "platforms"
    plat.mkdir(parents=True)
    (plat / "ambition.md").write_text("# Platform: ambition\n\ncivic forums and goal4\n", encoding="utf-8")
    papers = policy_card(
        policy=ensure_policy(tmp_path),
        campaign=campaign_text(tmp_path, "ambition"),
        due=True,
        editor="continuity",
        edited_turn=1,
    )
    assert "Nation policy" in papers
    assert "civic forums and goal4" in papers
    assert "you just took this office" in papers
    prez = snapshot_user(
        member_id="ambition",
        constitution=CONSTITUTION,
        gov=gov,
        members=FOUNDING_MEMBERS,
        goals_md="# Goals\n",
        open_motion=None,
        digest="",
        petitions=[],
        turn=3,
        office_papers=papers,
    )
    floor = snapshot_user(
        member_id="builder",
        constitution=CONSTITUTION,
        gov=gov,
        members=FOUNDING_MEMBERS,
        goals_md="# Goals\n",
        open_motion=None,
        digest="",
        petitions=[],
        turn=3,
        office_papers=papers,
    )
    assert "civic forums and goal4" in prez
    assert "edit_policy" in prez
    assert "civic forums and goal4" not in floor
    assert "Nation policy (private" not in floor


def test_coerce_edit_policy_accepts_string_body():
    fx = coerce_effects({"edit_policy": DEFAULT_POLICY + "\nKeep the inherited brief.\n"})[0]
    assert fx["type"] == "edit_policy"
    assert "inherited brief" in fx["body"]


def test_save_policy_roundtrip(tmp_path):
    ensure_policy(tmp_path)
    old = save_policy(tmp_path, "# Nation policy\n\nRevised by builder.\n")
    assert "Founded empty" in old
    assert load_policy(tmp_path).startswith("# Nation policy")

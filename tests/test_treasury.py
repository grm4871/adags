from adags.constitution import default_constitution
from adags.relations import format_standing, note, update_from_act
from adags.treasury import (
    card,
    gate_add_member,
    init,
    load,
    settle,
)


def _law(**overrides):
    law = default_constitution()
    mech = law["rules"]["213"]["mechanics"]
    mech.update(overrides)
    return law


def test_goal_yield_pays_once_not_every_turn(tmp_path):
    root = tmp_path
    init(root, law=_law())
    clock = "goal1 complete 2/2 files, due turn 9"
    first = settle(
        root, law=_law(), turn=3, n_members=5, goals={"goal1": "x"}, goal_clock_text=clock
    )
    assert any("complete" in note for note in first)
    balance_after_first = load(root)["credits"]
    second = settle(
        root, law=_law(), turn=4, n_members=5, goals={"goal1": "x"}, goal_clock_text=clock
    )
    assert not any("complete" in note for note in second)
    # upkeep still applies on the second turn, offset by the dividend (+1)
    assert load(root)["credits"] == balance_after_first - 5 + 1


def test_deficit_blocks_add_member_and_card_says_so(tmp_path):
    root = tmp_path
    init(root, law=_law())
    data = load(root)
    data["credits"] = -4
    import json

    (root / "treasury.json").write_text(json.dumps(data), encoding="utf-8")
    refusal = gate_add_member(root, law=_law())
    assert refusal and "refused" in refusal
    assert "DEFICIT" in card(root, law=_law())


def test_solvent_chapter_allows_add_member(tmp_path):
    root = tmp_path
    init(root, law=_law())
    assert gate_add_member(root, law=_law()) is None


def test_disabled_economy_is_inert(tmp_path):
    root = tmp_path
    notes = settle(
        root,
        law=_law(**{"economy.enabled": False}),
        turn=1,
        n_members=5,
        goals={},
        goal_clock_text="",
    )
    assert notes == []
    assert gate_add_member(root, law=_law(**{"economy.enabled": False})) is None


def test_relations_update_from_act():
    relations: dict = {}
    act = {
        "whisper": {"to": "builder", "body": "vote with me"},
        "nominate": {"member": "skeptic"},
        "impeach": "207",
        "speech": "I thank builder for the plan.",
    }

    def party_of(_mid: str) -> str:
        return ""

    update_from_act(
        relations,
        actor="ambition",
        act=act,
        seated=["ambition", "builder", "skeptic", "continuity"],
        president="continuity",
        member_party_of=party_of,
    )
    row = relations["ambition"]
    assert row["builder"] > 0  # whisper + speech mention
    assert row["skeptic"] > 0  # nomination bond
    assert row["continuity"] < 0  # impeachment slight
    assert "ambition" not in row  # never self


def test_standing_hides_weak_signal_and_self():
    relations: dict = {}
    note(relations, "skeptic", "builder", 0.2)  # below threshold
    note(relations, "skeptic", "ambition", -2.0)
    note(relations, "ambition", "skeptic", 1.5)
    # From builder's seat: skeptic's weak +0.2 toward builder stays hidden.
    text = format_standing(relations, "builder", ["skeptic", "builder", "ambition"])
    assert text == ""
    # From skeptic's seat: ambition cools toward them; they warm toward ambition.
    text = format_standing(relations, "skeptic", ["skeptic", "builder", "ambition"])
    assert "ambition (warm +1.5)" in text.split("You currently lean:")[0]
    assert "ambition (cool -2)" in text.split("You currently lean:")[1]
    assert "skeptic" not in text.split("You currently lean:")[1]

from adags.gov import (
    add_nominee,
    advance_phase,
    election_due,
    passes,
    plurality_winner,
    seat_president,
    term_expired,
    vacate_president,
)
from adags.seed import FOUNDING_MEMBERS, default_gov


def test_majority_threshold():
    assert passes(3, 5, "majority")
    assert not passes(2, 5, "majority")
    assert passes(5, 5, "unanimous")
    assert not passes(4, 5, "unanimous")


def test_party_join_leave_and_roster():
    from adags.gov import apply_party, as_party_id, party_roster
    from adags.seed import FOUNDING_MEMBERS

    assert as_party_id("Reform") == "reform"
    assert as_party_id("none") == ""
    assert as_party_id(None) is None
    members = apply_party(FOUNDING_MEMBERS, "ambition", "reform")
    members = apply_party(members, "builder", "reform")
    members = apply_party(members, "restraint", "caution")
    roster = party_roster(members)
    assert roster["reform"] == ["ambition", "builder"]
    assert roster["caution"] == ["restraint"]
    members = apply_party(members, "builder", "")
    assert "builder" not in party_roster(members)["reform"]


def test_as_flag_ignores_false_string():
    from adags.gov import as_flag

    assert as_flag(True) is True
    assert as_flag("true") is True
    assert as_flag("false") is False
    assert as_flag(False) is False
    assert as_flag(None) is False


def test_as_member_id_from_objects_and_repr():
    from adags.gov import as_member_id

    assert as_member_id("builder") == "builder"
    assert as_member_id({"member": "builder"}) == "builder"
    assert as_member_id({"vote": {"id": "restraint"}}) == "restraint"
    assert as_member_id("{'member': 'builder'}") == "builder"
    assert as_member_id('{"member": "builder"}') == "builder"
    assert as_member_id("not a candidate") is None


def test_plurality_accepts_object_votes():
    nominees = [{"member": "builder"}, {"member": "ambition"}]
    votes = {
        "continuity": {"member": "builder"},
        "ambition": "{'member': 'ambition'}",
        "restraint": {"member": "builder"},
    }
    assert plurality_winner(votes, nominees) == "builder"


def test_plurality_earliest_nomination_wins_tie():
    nominees = [
        {"member": "ambition", "platform": "a"},
        {"member": "builder", "platform": "b"},
    ]
    votes = {"continuity": "ambition", "restraint": "builder", "skeptic": "nope"}
    assert plurality_winner(votes, nominees) == "ambition"


def test_election_due_when_vacant():
    gov = default_gov()
    assert election_due(gov, 1)
    gov = seat_president(gov, "ambition", 2)
    assert not election_due(gov, 3)
    assert not election_due(gov, 5)
    assert term_expired(gov, 6)
    assert election_due(gov, 6)


def test_caretaker_then_ballot():
    gov = default_gov()
    gov = advance_phase(gov, 1)
    assert gov["election_phase"] == "nominate"
    gov = add_nominee(gov, member="ambition", platform="go", nominator="ambition", turn=1)
    assert not isinstance(gov, str)
    gov = advance_phase(gov, 2)
    assert gov["election_phase"] == "ballot"


def test_impeach_vacates():
    gov = seat_president(default_gov(), "ambition", 1)
    gov = vacate_president(gov)
    assert gov["offices"]["president"]["holder"] is None
    assert gov["election_phase"] == "nominate"

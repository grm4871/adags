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


def test_as_impeach_reads_article_ids():
    from adags.gov import as_impeach

    assert as_impeach(True) == (True, None)
    assert as_impeach(False) == (False, None)
    assert as_impeach("303") == (True, "303")
    assert as_impeach("article 307") == (True, "307")
    assert as_impeach(303) == (True, "303")
    assert as_impeach({"article": "304"}) == (True, "304")
    assert as_impeach({"charge": 209}) == (True, "209")
    assert as_impeach("true") == (True, None)
    assert as_impeach("no") == (False, None)
    assert as_impeach("101") == (False, None)


def test_advance_phase_waits_on_open_motion():
    gov = seat_president(default_gov(), "ambition", 1)
    due = advance_phase(gov, 9)
    assert due["election_phase"] == "nominate"
    waiting = advance_phase(gov, 9, motion_open=True)
    assert waiting["election_phase"] == "idle"
    already = dict(due)
    already["election_phase"] = "nominate"
    already["nominees"] = [{"member": "builder"}]
    keep = advance_phase(already, 10, motion_open=True)
    assert keep["election_phase"] == "ballot"


def test_as_member_id_from_objects_and_repr():
    from adags.gov import as_member_id

    assert as_member_id("builder") == "builder"
    assert as_member_id({"member": "builder"}) == "builder"
    assert as_member_id({"vote": {"id": "restraint"}}) == "restraint"
    assert as_member_id("{'member': 'builder'}") == "builder"
    assert as_member_id('{"member": "builder"}') == "builder"
    assert as_member_id("not a candidate") is None
    assert as_member_id({"voter": "open", "nominee": "builder"}) == "builder"
    assert as_member_id("a") is None
    assert as_member_id("any") is None
    assert as_member_id("phase") is None


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
    assert not election_due(gov, 9)
    assert term_expired(gov, 10)
    assert election_due(gov, 10)


def test_incumbent_cannot_be_renominated():
    from adags.gov import add_nominee, consecutive_blocked

    gov = seat_president(default_gov(), "ambition", 1)
    gov["election_phase"] = "nominate"
    assert consecutive_blocked(gov) == "ambition"
    denied = add_nominee(gov, member="ambition", platform="again", nominator="ambition", turn=9)
    assert denied == "ambition is ineligible this election (consecutive term)"
    ok = add_nominee(gov, member="builder", platform="other", nominator="builder", turn=9)
    assert not isinstance(ok, str)


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

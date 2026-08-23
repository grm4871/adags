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


def test_seat_summary_names_tie_break():
    from adags.gov import seat_summary

    nominees = [{"member": "assistant"}, {"member": "restraint"}]
    votes = {"minority": "assistant", "assistant": "assistant", "restraint": "restraint", "continuity": "restraint"}
    assert (
        seat_summary(votes, nominees, "assistant")
        == "seated assistant (assistant 2, restraint 2; tie → earliest nominee)"
    )


def _party_members(assignments: dict[str, str]) -> list[dict]:
    from copy import deepcopy

    members = deepcopy(FOUNDING_MEMBERS)
    for member in members:
        if member["id"] in assignments:
            member["party"] = assignments[member["id"]]
    return members


def test_caucus_primary_locks_ticket_and_seconds_later_noms():
    gov = default_gov()
    members = _party_members(
        {"continuity": "forward", "skeptic": "forward", "builder": "forward", "ambition": "rise"}
    )
    gov = add_nominee(
        gov,
        member="skeptic",
        platform="audit",
        nominator="continuity",
        turn=10,
        members=members,
    )
    assert not isinstance(gov, str)
    assert gov["party_tickets"]["forward"] == "skeptic"
    second = add_nominee(
        gov,
        member="builder",
        platform="tools",
        nominator="builder",
        turn=10,
        members=members,
    )
    assert second == "seconded skeptic (forward ticket)"
    assert {n["member"] for n in gov["nominees"]} == {"skeptic"}
    rise = add_nominee(
        gov,
        member="ambition",
        platform="forums",
        nominator="ambition",
        turn=10,
        members=members,
    )
    assert not isinstance(rise, str)
    assert rise["party_tickets"]["rise"] == "ambition"
    assert {n["member"] for n in rise["nominees"]} == {"skeptic", "ambition"}


def test_caucus_bolt_lets_a_member_run_separately():
    gov = default_gov()
    members = _party_members({"continuity": "forward", "builder": "forward"})
    gov = add_nominee(
        gov,
        member="continuity",
        platform="keep",
        nominator="continuity",
        turn=10,
        members=members,
    )
    assert not isinstance(gov, str)
    bolted = [dict(m) for m in members]
    for member in bolted:
        if member["id"] == "builder":
            member.pop("party", None)
    gov = add_nominee(
        gov,
        member="builder",
        platform="bolt",
        nominator="builder",
        turn=10,
        members=bolted,
    )
    assert not isinstance(gov, str)
    assert {n["member"] for n in gov["nominees"]} == {"continuity", "builder"}
    assert gov["party_tickets"] == {"forward": "continuity"}


def test_caucus_ballot_remaps_self_vote_but_keeps_cross_endorsement():
    from adags.gov import apply_caucus_ballot

    gov = default_gov()
    gov["party_tickets"] = {"forward": "skeptic"}
    members = _party_members({"builder": "forward", "continuity": "forward"})
    pick, note = apply_caucus_ballot("builder", "builder", members, gov)
    assert pick == "skeptic"
    assert note and "skeptic" in note
    pick, note = apply_caucus_ballot("continuity", "restraint", members, gov)
    assert pick == "restraint"
    assert note is None


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

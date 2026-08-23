from adags.constitution import mechanics, set_mechanic
from adags.founding import roll_founding
from adags.state import init_run


def test_seeded_founding_is_reproducible(tmp_path):
    a = roll_founding(__import__("random").Random(7))
    b = roll_founding(__import__("random").Random(7))
    assert a == b


def test_two_seeds_differ(tmp_path):
    rolls = [roll_founding(__import__("random").Random(s)) for s in range(8)]
    keys = {
        (
            tuple(m["id"] for m in r["members"]),
            r["mechanics"]["election.term_length"],
            r["mechanics"]["economy.goal_complete_yield"],
        )
        for r in rolls
    }
    # With 10 personas, varied knobs, and 5 directives, eight seeds must not all collide.
    assert len(keys) >= 4


def test_random_init_writes_rolled_law_and_members(tmp_path):
    state = init_run(tmp_path / "run", found=3)
    ids = [m["id"] for m in state.members()]
    assert len(ids) in (5, 6)
    assert "continuity" in ids  # journal keeper always seated
    law = state.law()
    mech = mechanics(law)
    assert mech["election.term_length"] in range(4, 11)
    assert mech["economy.member_upkeep"] in (1, 2)
    gov = state.gov()
    assert gov["term_length"] == mech["election.term_length"]
    assert gov["vote_rule"] == mech["motion.threshold"]


def test_classic_found_untouched_by_default(tmp_path):
    state = init_run(tmp_path / "run")
    ids = [m["id"] for m in state.members()]
    assert ids == ["continuity", "ambition", "restraint", "skeptic", "builder"]
    assert state.gov()["term_length"] == 8


def test_set_mechanic_updates_owner_rule():
    law = {"rules": {"201": {"mechanics": {"motion.threshold": "majority"}}}}
    out = set_mechanic(law, "motion.threshold", "two_thirds")
    assert out["rules"]["201"]["mechanics"]["motion.threshold"] == "two_thirds"

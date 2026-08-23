from adags.gov import seat_president
from adags.host import run_turn
from adags.llm import ScriptedLLM
from adags.seed import CONSTITUTION, FOUNDING_MEMBERS, default_gov
from adags.state import init_run
from adags.citizens import snapshot_user
from adags.whispers import format_inbox, format_whisper_log, parse_whisper


def test_parse_whisper_requires_a_real_recipient():
    seated = ["continuity", "builder", "ambition"]
    assert parse_whisper(None, sender="continuity", seated=seated) is None
    assert isinstance(parse_whisper({"to": "builder"}, sender="continuity", seated=seated), str)
    assert parse_whisper({"to": "continuity", "body": "hi"}, sender="continuity", seated=seated)
    note = parse_whisper(
        {"to": "builder", "body": "vote the forward ticket"},
        sender="continuity",
        seated=seated,
    )
    assert note["to"] == "builder"
    assert "forward" in note["body"]
    assert "ignored" in parse_whisper(
        {"to": "builder", "body": "We need to produce a JSON object with speech."},
        sender="continuity",
        seated=seated,
    )


def test_snapshot_shows_inbox_only_to_the_recipient():
    inbox = format_inbox(
        [{"from": "continuity", "to": "builder", "body": "vote skeptic; I will too"}]
    )
    gov = default_gov()
    gov["election_phase"] = "ballot"
    user = snapshot_user(
        member_id="builder",
        constitution=CONSTITUTION,
        gov=gov,
        members=FOUNDING_MEMBERS,
        goals_md="# Goals\n",
        open_motion=None,
        digest="",
        petitions=[],
        turn=3,
        whispers_md=inbox,
    )
    floor = snapshot_user(
        member_id="ambition",
        constitution=CONSTITUTION,
        gov=gov,
        members=FOUNDING_MEMBERS,
        goals_md="# Goals\n",
        open_motion=None,
        digest="",
        petitions=[],
        turn=3,
    )
    assert "vote skeptic; I will too" in user
    assert "the floor does not hear" in user
    assert "vote skeptic; I will too" not in floor


def test_whisper_lands_same_turn_and_stays_out_of_the_digest(tmp_path):
    state = init_run(tmp_path / "run", turn_cap=4, usd_cap=1.0)
    gov = seat_president(state.gov(), "ambition", 1)
    gov["policy_due"] = False
    state.write_gov(gov)
    state.write_goals({"g1": "Keep a live objective."})
    scripts = []
    for mid in ["continuity", "ambition", "restraint", "skeptic", "builder"]:
        scripts.append(
            {
                "speech": f"{mid} acts.",
                "nominate": None,
                "vote_election": None,
                "impeach": False,
                "propose": None,
                "vote_motion": None,
                "executive": None,
                "whisper": (
                    {"to": "builder", "body": "vote skeptic next ballot"}
                    if mid == "continuity"
                    else None
                ),
            }
        )
    run_turn(state, ScriptedLLM(scripts=scripts))
    log = (state.root / "whispers.jsonl").read_text(encoding="utf-8")
    assert "vote skeptic next ballot" in log
    digest = state.path("journal.md").read_text(encoding="utf-8")
    assert "continuity→builder" in digest
    assert "vote skeptic next ballot" not in digest
    assert format_whisper_log(
        [{"from": "continuity", "to": "builder", "body": "secret"}]
    ) == "continuity→builder"


def test_invalid_register_is_vacant():
    from adags.effects import goals_are_vacant

    assert goals_are_vacant({})
    assert goals_are_vacant(
        {
            "speech-goal": "and write a workspace as required by offices.president.privileges (host article 207)."
        }
    )
    assert not goals_are_vacant({"goal2": "safeguard minority voices"})

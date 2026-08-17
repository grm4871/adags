from adags.memory import (
    append_record,
    compose_user,
    format_record,
    history_prefix,
    load_records,
    record_from_act,
)


def test_history_prefix_only_grows_by_append():
    r1 = {"turn": 18, "vote": "builder", "speech": "I vote builder."}
    r2 = {"turn": 19, "motion": "aye"}
    a = history_prefix([r1])
    b = history_prefix([r1, r2])
    assert b.startswith(a)
    assert a.startswith(history_prefix([]))


def test_record_from_act_skips_protocol_and_objects():
    rec = record_from_act(
        25,
        {
            "speech": "I vote aye on the privilege bill.",
            "nominate": {"member": "builder"},
            "vote_election": {"member": "builder"},
            "impeach": "false",
            "propose": None,
            "vote_motion": {"choice": "aye"},
            "executive": [{"type": "set_goal", "id": "g1"}],
        },
    )
    assert rec["turn"] == 25
    assert rec["nominate"] == "builder"
    assert rec["vote"] == "builder"
    assert rec.get("impeach") is None
    assert rec["motion"] == "aye"
    assert rec["exec"] == ["set_goal"]
    line = format_record(rec)
    assert "voted builder" in line
    assert "nominated builder" in line


def test_compose_puts_snapshot_last_and_roundtrips(tmp_path):
    append_record(tmp_path, "continuity", {"turn": 10, "vote": "continuity"})
    append_record(tmp_path, "continuity", {"turn": 18, "exec": ["set_goal"]})
    recs = load_records(tmp_path, "continuity")
    assert len(recs) == 2
    user = compose_user(recs, "Turn 33. phase ballot.")
    assert user.index("## Your acts") < user.index("## This turn")
    assert user.strip().endswith("Turn 33. phase ballot.")
    assert "t10 · voted continuity" in user
    assert "t18 · exec set_goal" in user

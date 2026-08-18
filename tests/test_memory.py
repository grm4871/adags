from adags.memory import (
    append_record,
    compose_user,
    format_record,
    history_prefix,
    load_records,
    patch_last_record,
    record_from_act,
    workspace_card,
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

    shaped = record_from_act(
        26,
        {
            "speech": "I set the goal.",
            "executive": {"set_goal": "Keep a written log.", "write_workspace": "minute"},
            "scratch": "next: amend 201 with motion.threshold two_thirds",
        },
    )
    assert shaped["exec"] == ["set_goal", "write_workspace"]
    assert "motion.threshold" in shaped["scratch"]
    assert "scratch" in format_record(shaped)


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


def test_patch_last_record_keeps_prior_bytes(tmp_path):
    append_record(tmp_path, "continuity", {"turn": 10, "vote": "continuity"})
    append_record(tmp_path, "continuity", {"turn": 11, "bill": "untitled"})
    before = (tmp_path / "memory" / "continuity.jsonl").read_bytes()
    first = before.splitlines()[0]
    patch_last_record(tmp_path, "continuity", 11, host="opened m11 with no structured effects")
    after = (tmp_path / "memory" / "continuity.jsonl").read_bytes()
    assert after.splitlines()[0] == first
    recs = load_records(tmp_path, "continuity")
    assert "no structured effects" in recs[-1]["host"]
    patch_last_record(tmp_path, "continuity", 11, host="bill passed 4-1: clerk empty")
    recs = load_records(tmp_path, "continuity")
    assert recs[-1]["host"].startswith("opened m11")
    assert "bill passed" in recs[-1]["host"]


def test_workspace_card_lists_heads(tmp_path):
    (tmp_path / "design-log.md").write_text("constitutional stewardship\n", encoding="utf-8")
    card = workspace_card(tmp_path)
    assert "design-log.md" in card
    assert "constitutional stewardship" in card


def test_clerk_brief_every_fourth_turn_and_card_uses_exact_speech_once(tmp_path):
    from adags.brief import digest_for_card, due, maybe_clerk_brief, recent_journal

    assert due(4) is True
    assert due(5) is False
    journal = "## Turn 1\nhello\n\n## Turn 2\nworld\n\n## Turn 3\nmore\n"
    assert "Turn 2" in recent_journal(journal, turns=2)
    assert "Turn 1" not in recent_journal(journal, turns=2)

    class Fake:
        def path(self, name):
            return tmp_path / name

    (tmp_path / "journal.md").write_text(journal, encoding="utf-8")
    text = maybe_clerk_brief(
        Fake(),
        turn=4,
        mechanical="raw",
        runner=lambda _user: "Ambition sat. The 316 clone died as already-law. Ten goals remain.",
    )
    assert text and "already-law" in text
    digest = (
        "# Clerk brief (turns 1–4)\n\nOffice changed hands.\n\n---\n\n"
        "# Turn 4 digest\n\n## Speech\n**builder:** recap\n**ambition:** dissent\n\n"
        "Impeach marks: none\n"
    )
    card = digest_for_card(digest)
    assert "Office changed hands" not in card
    assert card.count("recap") == 1
    assert "dissent" in card

    ambition_card = digest_for_card(digest, exclude_member="ambition")
    assert "dissent" not in ambition_card
    assert "recap" in ambition_card


def test_goal_clock_counts_files_and_due_date(tmp_path):
    from adags.memory import goal_clock, goal_until

    assert goal_until("Keep a civic journal until turn 12.") == 12
    (tmp_path / "journal").mkdir()
    (tmp_path / "journal" / "turn5.md").write_text("civic journal entry for g1\n", encoding="utf-8")
    (tmp_path / "note.md").write_text("unrelated minutes\n", encoding="utf-8")
    clock = goal_clock(
        {"g1": "Keep a civic journal until turn 12."},
        tmp_path,
        turn=8,
    )
    assert "g1 open 1/3 files, due turn 12" in clock
    (tmp_path / "journal" / "turn8.md").write_text("g1 civic journal\n", encoding="utf-8")
    (tmp_path / "journal" / "turn10.md").write_text("more civic journal for g1\n", encoding="utf-8")
    done = goal_clock(
        {"g1": "Keep a civic journal until turn 12."},
        tmp_path,
        turn=8,
    )
    assert "g1 complete 3/3 files" in done
    late = goal_clock(
        {"g1": "Keep a civic journal until turn 6."},
        tmp_path,
        turn=8,
    )
    assert "g1 complete 3/3 files" in late
    emptyish = goal_clock(
        {"g2": "Ship a prototype until turn 4."},
        tmp_path,
        turn=8,
    )
    assert "g2 overdue 0/3 files, due turn 4" in emptyish


def test_goal_clock_ignores_old_slogan_files(tmp_path):
    import time

    from adags.memory import goal_clock

    old = tmp_path / "artifacts"
    old.mkdir()
    prior = old / "first.md"
    prior.write_text("chamber artifact naming the active goal\n", encoding="utf-8")
    meta = {
        "goal4": {
            "since_turn": 20,
            "baseline": {"artifacts/first.md": prior.stat().st_mtime},
        }
    }
    clock = goal_clock(
        {"goal4": "Build two artifacts naming the active goal."},
        tmp_path,
        turn=21,
        meta=meta,
    )
    assert "goal4 open 0/3 files" in clock
    time.sleep(0.02)
    (old / "fourth.md").write_text("this file names goal4 explicitly\n", encoding="utf-8")
    clock = goal_clock(
        {"goal4": "Build two artifacts naming the active goal."},
        tmp_path,
        turn=21,
        meta=meta,
    )
    assert "goal4 open 1/3 files" in clock

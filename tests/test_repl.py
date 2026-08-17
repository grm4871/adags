from adags.repl import parse_line
from adags.render import journal_tail, status_block, suggestions_text
from adags.state import RunState, archive_run, init_run
from adags.seed import default_gov
from adags.cli import main


def test_parse_slash_and_plain():
    assert parse_line("/status").name == "status"
    assert parse_line("run 2 --mock").name == "run"
    assert parse_line("run 2 --mock").args == ["2", "--mock"]
    assert parse_line("   ") is None


def test_status_and_journal_render(tmp_path):
    state = init_run(tmp_path / "run")
    text = status_block(state)
    assert "ADAGS" in text
    assert "continuity" in text
    assert "t1/" not in text
    assert "turn 1" in text
    state.path("journal.md").write_text(
        "# Journal\n\n## Turn 1\none\n\n## Turn 2\ntwo\n",
        encoding="utf-8",
    )
    tail = journal_tail(state, 1)
    assert "Turn 2" in tail
    assert "Turn 1" not in tail


def test_archive_run_moves_and_can_reinit(tmp_path):
    root = tmp_path / "run"
    init_run(root, turn_cap=8, usd_cap=1.0)
    (root / "journal.md").write_text("# old nation\n", encoding="utf-8")
    dest = archive_run(root, label="founding")
    assert dest.is_dir()
    assert "founding" in dest.name
    assert not root.exists()
    assert (dest / "journal.md").read_text() == "# old nation\n"
    init_run(root, turn_cap=12, usd_cap=1.0)
    assert (root / "control.json").exists()
    assert "old nation" not in (root / "journal.md").read_text()


def test_global_run_dir_before_subcommand_is_preserved(tmp_path):
    root = tmp_path / "custom"
    assert main(["--run-dir", str(root), "init"]) == 0
    assert (root / "control.json").exists()


def test_empty_suggestion_box(tmp_path):
    state = init_run(tmp_path / "run")
    assert suggestions_text(state) == "(suggestion box empty)"


def test_legacy_government_migrates_to_executable_constitution(tmp_path):
    root = tmp_path / "legacy"
    root.mkdir()
    state = RunState(root)
    gov = default_gov()
    gov["vote_rule"] = "two_thirds"
    gov["term_length"] = 9
    state.write_gov(gov)
    law = state.law()
    assert law["rules"]["201"]["mechanics"]["motion.threshold"] == "two_thirds"
    assert law["rules"]["208"]["mechanics"]["election.term_length"] == 9
    assert (root / "constitution.json").exists()

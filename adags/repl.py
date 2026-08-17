"""Interactive operator harness. `adags` with no subcommand."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from adags.render import (
    REPL_HELP,
    banner,
    digest_text,
    doctor_text,
    goals_text,
    journal_tail,
    law_text,
    members_text,
    status_block,
    suggestions_text,
)
from adags.state import RunState, archive_run, init_run


@dataclass
class ReplCmd:
    name: str
    args: list[str]


def parse_line(line: str) -> ReplCmd | None:
    text = line.strip()
    if not text:
        return None
    if text.startswith("/"):
        text = text[1:]
    if not text:
        return None
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    return ReplCmd(name=parts[0].lower(), args=parts[1:])


def dispatch(state: RunState, cmd: ReplCmd, *, root: Path) -> tuple[str, bool]:
    """Return (output, should_quit)."""
    n = cmd.name
    if n in {"quit", "exit", "q"}:
        return "bye", True
    if n in {"help", "h", "?"}:
        return REPL_HELP, False
    if n in {"status", "st"}:
        return status_block(state), False
    if n in {"journal", "log"}:
        k = int(cmd.args[0]) if cmd.args and cmd.args[0].isdigit() else 2
        return journal_tail(state, k), False
    if n == "digest":
        return digest_text(state), False
    if n in {"law", "constitution", "const"}:
        return law_text(state), False
    if n in {"goals", "goal"}:
        return goals_text(state), False
    if n in {"members", "who"}:
        return members_text(state), False
    if n in {"suggestions", "suggestion", "box"}:
        return suggestions_text(state), False
    if n == "doctor":
        return doctor_text(), False
    if n == "banner":
        return banner(state), False
    if n == "init":
        if state.path("control.json").exists():
            return "run already exists", False
        init_run(root)
        return status_block(RunState(root)), False
    if n == "archive":
        if not state.path("control.json").exists():
            return "no run to archive", False
        label = " ".join(cmd.args).strip() or None
        dest = archive_run(root, label=label)
        init_run(root)
        return f"archived → {dest}\n{status_block(RunState(root))}", False
    if n == "pause":
        from adags.cli import _pause

        return _pause(state), False
    if n == "resume":
        from adags.cli import _resume

        return _resume(state), False
    if n == "veto":
        from adags.host import veto_last

        return veto_last(state), False
    if n == "petition":
        text = " ".join(cmd.args).strip()
        if not text:
            return "usage: petition <text>", False
        from adags.cli import _file_petition

        return _file_petition(state, text), False
    if n == "run":
        turns = 1
        mock = False
        if cmd.args:
            if cmd.args[0].isdigit():
                turns = int(cmd.args[0])
            if "--mock" in cmd.args:
                mock = True
        from adags.cli import _run_turns

        _run_turns(state, turns=turns, mock=mock)
        return status_block(RunState(state.root)), False
    return f"unknown command {n!r}  —  /help", False


def loop(root: Path) -> int:
    from adags.cli import _load_dotenv

    _load_dotenv()
    state = RunState(root)
    print(banner(state))
    print("operator harness.  /help  to list commands.")
    while True:
        try:
            line = input(f"{root.name}> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        parsed = parse_line(line)
        if parsed is None:
            continue
        state = RunState(root)
        out, done = dispatch(state, parsed, root=root)
        if out:
            print(out)
        if done:
            return 0

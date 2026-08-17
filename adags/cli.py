"""Operator CLI: init, run, pause, veto, petition, status."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import json

from adags.host import authorize_operator_turns, run_loop, veto_last
from adags.llm import ScriptedLLM, make_llm
from adags.state import RunState, archive_run, init_run


def _root(args: argparse.Namespace) -> Path:
    return Path(args.run_dir or os.environ.get("ADAGS_RUN_DIR", "run"))


def _load_dotenv() -> None:
    p = Path(".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _pause(state: RunState) -> str:
    c = state.control()
    c["paused"] = True
    state.write_control(c)
    return "paused"


def _resume(state: RunState) -> str:
    c = state.control()
    c["paused"] = False
    state.write_control(c)
    return "resumed — /run to continue"


def _file_petition(state: RunState, text: str) -> str:
    d = state.root / "petitions"
    d.mkdir(exist_ok=True)
    n = len(list(d.glob("*.md"))) + 1
    dest = d / f"{n:03d}.md"
    dest.write_text(text.strip() + "\n", encoding="utf-8")
    return f"filed {dest.name}"


def _run_turns(
    state: RunState,
    *,
    turns: int | None,
    mock: bool = False,
    turn_cap: int | None = None,
    usd_cap: float | None = None,
    max_seconds: float | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    _load_dotenv()
    control = state.control()
    turns = authorize_operator_turns(control, turns=turns, turn_cap=turn_cap)
    if usd_cap is not None:
        control["usd_cap"] = usd_cap
    if usd_cap is None and float(control.get("usd_cap") or 0) > 2:
        control["usd_cap"] = 1.0
    state.write_control(control)
    llm = ScriptedLLM() if mock else make_llm(provider=provider, model=model)
    run_loop(state, llm, turns=turns, max_seconds=max_seconds)


def cmd_archive(args: argparse.Namespace) -> int:
    root = _root(args)
    dest = archive_run(root, label=args.label)
    print(f"archived {root} → {dest}")
    if args.init:
        state = init_run(root, turn_cap=args.turn_cap, usd_cap=args.usd_cap)
        print(f"initialized {state.root}")
        print(f"founding members: {', '.join(m['id'] for m in state.members())}")
        print("presidency vacant; first turn is nominations")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    state = init_run(_root(args), turn_cap=args.turn_cap, usd_cap=args.usd_cap)
    print(f"initialized {state.root}")
    print(f"founding members: {', '.join(m['id'] for m in state.members())}")
    print("presidency vacant; first turn is nominations")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    root = _root(args)
    if not (root / "control.json").exists():
        init_run(root, turn_cap=args.turn_cap, usd_cap=args.usd_cap if args.usd_cap is not None else 1.0)
    state = RunState(root)
    _run_turns(
        state,
        turns=args.turns,
        mock=args.mock,
        turn_cap=args.turn_cap,
        usd_cap=args.usd_cap,
        max_seconds=args.max_seconds,
        provider=args.provider,
        model=args.model,
    )
    from adags.render import status_block

    print(status_block(RunState(root)), flush=True)
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    print(_pause(RunState(_root(args))))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    print(_resume(RunState(_root(args))))
    return 0


def cmd_veto(args: argparse.Namespace) -> int:
    print(veto_last(RunState(_root(args))))
    return 0


def cmd_petition(args: argparse.Namespace) -> int:
    text = args.text
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    if not text:
        raise SystemExit("provide --text or --file")
    print(_file_petition(RunState(_root(args)), text))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from adags.render import status_block

    print(status_block(RunState(_root(args))))
    return 0


def cmd_journal(args: argparse.Namespace) -> int:
    from adags.render import journal_tail

    print(journal_tail(RunState(_root(args)), args.turns))
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    from adags.render import digest_text

    print(digest_text(RunState(_root(args))))
    return 0


def cmd_law(args: argparse.Namespace) -> int:
    from adags.render import law_text

    print(law_text(RunState(_root(args))))
    return 0


def cmd_goals(args: argparse.Namespace) -> int:
    from adags.render import goals_text

    print(goals_text(RunState(_root(args))))
    return 0


def cmd_members(args: argparse.Namespace) -> int:
    from adags.render import members_text

    print(members_text(RunState(_root(args))))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from adags.render import doctor_text

    _load_dotenv()
    print(doctor_text())
    return 0


def cmd_repl(args: argparse.Namespace) -> int:
    from adags.repl import loop

    return loop(_root(args))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="adags",
        description="ADAGS operator harness. No subcommand opens an interactive session.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--run-dir",
        default=argparse.SUPPRESS,
        help="run directory (default: $ADAGS_RUN_DIR or ./run)",
    )
    p.add_argument("--run-dir", default=None, help="run directory (default: $ADAGS_RUN_DIR or ./run)")
    sub = p.add_subparsers(dest="cmd", required=False)

    s = sub.add_parser("init", help="create a founding run", parents=[common])
    s.add_argument("--turn-cap", type=int, default=12)
    s.add_argument("--usd-cap", type=float, default=1.0, help="hard spend cap (default $1)")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("archive", help="move the current run to archive/", parents=[common])
    s.add_argument("label", nargs="?", default=None, help="optional slug on the archive folder")
    s.add_argument("--init", action="store_true", help="found a new run at the same path")
    s.add_argument("--turn-cap", type=int, default=12)
    s.add_argument("--usd-cap", type=float, default=1.0)
    s.set_defaults(func=cmd_archive)

    s = sub.add_parser("run", help="run turns until pause/cap", parents=[common])
    s.add_argument("--turns", type=int, default=None, help="max turns this invocation")
    s.add_argument("--turn-cap", type=int, default=None, help="set the run's turn ceiling (run N also lifts it)")
    s.add_argument("--usd-cap", type=float, default=None, help="hard spend cap (default $1 on init)")
    s.add_argument("--max-seconds", type=float, default=None, help="stop this invocation after N seconds")
    s.add_argument("--mock", action="store_true", help="scripted agents, no API")
    s.add_argument(
        "--provider",
        default=None,
        help="hermes (default, Nous Portal via CLI) | openrouter | openai | xai",
    )
    s.add_argument("--model", default=None)
    s.set_defaults(func=cmd_run)

    sub.add_parser("pause", parents=[common]).set_defaults(func=cmd_pause)
    sub.add_parser("resume", parents=[common]).set_defaults(func=cmd_resume)
    sub.add_parser("veto", help="reverse last reversible act", parents=[common]).set_defaults(func=cmd_veto)
    s = sub.add_parser("petition", help="inject a bill the polity may ignore", parents=[common])
    s.add_argument("--text", default=None)
    s.add_argument("--file", default=None)
    s.set_defaults(func=cmd_petition)
    sub.add_parser("status", parents=[common], help="run snapshot").set_defaults(func=cmd_status)
    s = sub.add_parser("journal", parents=[common], help="recent journal turns")
    s.add_argument("turns", nargs="?", type=int, default=2)
    s.set_defaults(func=cmd_journal)
    sub.add_parser("digest", parents=[common], help="last-turn digest").set_defaults(func=cmd_digest)
    sub.add_parser("law", parents=[common], help="constitution").set_defaults(func=cmd_law)
    sub.add_parser("goals", parents=[common], help="goal register").set_defaults(func=cmd_goals)
    sub.add_parser("members", parents=[common], help="seated citizens").set_defaults(func=cmd_members)
    sub.add_parser("doctor", parents=[common], help="check hermes/keys/provider").set_defaults(func=cmd_doctor)
    sub.add_parser("repl", parents=[common], help="interactive harness").set_defaults(func=cmd_repl)

    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        return cmd_repl(args)
    return args.func(args)

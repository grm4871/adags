"""File-backed run state."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from adags.constitution import default_constitution, render
from adags.effects import parse_goals, render_goals
from adags.seed import (
    FOUNDING_MEMBERS,
    GOALS_EMPTY,
    default_control,
    default_gov,
)


@dataclass
class RunState:
    root: Path

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    def path(self, name: str) -> Path:
        return self.root / name

    def load_json(self, name: str) -> Any:
        return json.loads(self.path(name).read_text(encoding="utf-8"))

    def dump_json(self, name: str, data: Any) -> None:
        self.path(name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def constitution(self) -> str:
        return render(self.law())

    def law(self) -> dict:
        path = self.path("constitution.json")
        if path.exists():
            return self.load_json("constitution.json")
        law = default_constitution()
        # One-time migration for runs created before executable constitutions.
        if self.path("gov.json").exists():
            gov = self.gov()
            law["rules"]["201"]["mechanics"]["motion.threshold"] = gov.get("vote_rule", "majority")
            law["rules"]["207"]["mechanics"]["offices.president.privileges"] = (
                (gov.get("offices") or {}).get("president", {}).get("privileges")
                or ["write_workspace", "set_goal"]
            )
            law["rules"]["208"]["mechanics"].update(
                {
                    "election.enabled": gov.get("election_enabled", True),
                    "election.method": gov.get("election_rule", "plurality"),
                    "election.term_length": gov.get("term_length", 4),
                }
            )
            law["rules"]["209"]["mechanics"]["impeachment.threshold"] = gov.get(
                "impeach_threshold", "majority"
            )
            law["rules"]["211"]["mechanics"]["membership.max_members"] = gov.get("max_members")
        self.write_law(law)
        return law

    def write_law(self, law: dict) -> None:
        self.dump_json("constitution.json", law)
        self.path("constitution.md").write_text(render(law), encoding="utf-8")

    def goals(self) -> dict[str, str]:
        p = self.path("goals.md")
        if not p.exists():
            return {}
        return parse_goals(p.read_text(encoding="utf-8"))

    def write_goals(self, goals: dict[str, str]) -> None:
        self.path("goals.md").write_text(render_goals(goals), encoding="utf-8")

    def members(self) -> list[dict]:
        return self.load_json("members.json")

    def write_members(self, members: list[dict]) -> None:
        self.dump_json("members.json", members)

    def gov(self) -> dict:
        return self.load_json("gov.json")

    def write_gov(self, gov: dict) -> None:
        self.dump_json("gov.json", gov)

    def control(self) -> dict:
        return self.load_json("control.json")

    def write_control(self, control: dict) -> None:
        self.dump_json("control.json", control)

    def append_journal(self, text: str) -> None:
        p = self.path("journal.md")
        with p.open("a", encoding="utf-8") as fh:
            fh.write(text)
            if not text.endswith("\n"):
                fh.write("\n")

    def last_digest(self) -> str:
        p = self.path("digest.md")
        if not p.exists():
            return "(no prior turn)"
        return p.read_text(encoding="utf-8")

    def write_digest(self, text: str) -> None:
        self.path("digest.md").write_text(text, encoding="utf-8")

    def append_act(self, act: dict) -> None:
        p = self.path("acts.jsonl")
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(act) + "\n")

    def last_act(self) -> dict | None:
        p = self.path("acts.jsonl")
        if not p.exists():
            return None
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])

    def petitions(self) -> list[str]:
        d = self.root / "petitions"
        if not d.exists():
            return []
        out = []
        for p in sorted(d.glob("*.md")):
            out.append(f"### {p.name}\n{p.read_text(encoding='utf-8').strip()}")
        return out


def init_run(root: Path, *, turn_cap: int = 12, usd_cap: float = 3.0) -> RunState:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "workspace" / "platforms").mkdir(parents=True, exist_ok=True)
    (root / "petitions").mkdir(exist_ok=True)
    (root / "motions").mkdir(exist_ok=True)
    (root / "suggestions").mkdir(exist_ok=True)
    state = RunState(root)
    state.write_law(state.law())
    if not state.path("goals.md").exists():
        state.path("goals.md").write_text(GOALS_EMPTY, encoding="utf-8")
    if not state.path("members.json").exists():
        state.write_members(FOUNDING_MEMBERS)
    if not state.path("gov.json").exists():
        state.write_gov(default_gov())
    if not state.path("control.json").exists():
        state.write_control(default_control(turn_cap=turn_cap, usd_cap=usd_cap))
    if not state.path("journal.md").exists():
        state.path("journal.md").write_text("# Journal\n\n", encoding="utf-8")
    if not state.path("acts.jsonl").exists():
        state.path("acts.jsonl").write_text("", encoding="utf-8")
    return state


def archive_run(root: Path, *, label: str | None = None) -> Path:
    """Move an existing run aside. Caller may init_run() on the same path after."""
    root = root.resolve()
    if not (root / "control.json").exists():
        raise FileNotFoundError(f"no run at {root}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = ""
    if label:
        slug = "-" + re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-")[:40]
        slug = slug.rstrip("-")
    dest = root.parent / "archive" / f"{root.name}-{stamp}{slug}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"archive already exists: {dest}")
    root.rename(dest)
    return dest

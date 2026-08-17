"""Append-only per-citizen act ledger. Prefix-stable for cache hits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adags.gov import as_flag, as_member_id
from adags.render import as_ballot, collapse_ws

PREAMBLE = (
    "Your own acts, oldest first. Do not recap them. "
    "If THIS TURN disagrees with an older line, THIS TURN is true.\n"
    "\n"
    "## Your acts"
)


def memory_file(root: Path, member_id: str) -> Path:
    return root / "memory" / f"{member_id}.jsonl"


def load_records(root: Path, member_id: str) -> list[dict[str, Any]]:
    path = memory_file(root, member_id)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def append_record(root: Path, member_id: str, record: dict[str, Any]) -> None:
    path = memory_file(root, member_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def record_from_act(turn: int, act: dict[str, Any]) -> dict[str, Any]:
    rec: dict[str, Any] = {"turn": int(turn)}
    speech = collapse_ws(str(act.get("speech") or ""))
    if speech and not speech.startswith("("):
        rec["speech"] = speech[:200]
    nom = act.get("nominate")
    if isinstance(nom, dict):
        who = as_member_id(nom.get("member")) or as_member_id(nom)
        if who:
            rec["nominate"] = who
    vote = as_member_id(act.get("vote_election"))
    if vote:
        rec["vote"] = vote
    if as_flag(act.get("impeach")):
        rec["impeach"] = True
    prop = act.get("propose")
    if isinstance(prop, dict) and (prop.get("title") or prop.get("effects")):
        rec["bill"] = collapse_ws(str(prop.get("title") or "untitled"))[:80]
    ballot = as_ballot(act.get("vote_motion"))
    if ballot:
        rec["motion"] = ballot
    if act.get("party") is not None:
        from adags.gov import as_party_id

        slug = as_party_id(act.get("party"))
        if slug:
            rec["party"] = slug
        elif slug == "":
            rec["party"] = "none"
    exec_fx = act.get("executive")
    if isinstance(exec_fx, list) and exec_fx:
        kinds = []
        for fx in exec_fx:
            if isinstance(fx, dict) and fx.get("type"):
                kinds.append(str(fx["type"]))
        if kinds:
            rec["exec"] = kinds
    return rec


def format_record(record: dict[str, Any]) -> str:
    bits = [f"t{record.get('turn', '?')}"]
    if record.get("nominate"):
        bits.append(f"nominated {record['nominate']}")
    if record.get("vote"):
        bits.append(f"voted {record['vote']}")
    if record.get("impeach"):
        bits.append("impeach")
    if record.get("bill"):
        bits.append(f"bill {record['bill']}")
    if record.get("motion"):
        bits.append(record["motion"])
    if record.get("exec"):
        bits.append("exec " + ",".join(record["exec"]))
    if record.get("party"):
        bits.append("party " + str(record["party"]))
    speech = collapse_ws(str(record.get("speech") or ""))
    if speech:
        bits.append(speech[:160])
    if len(bits) == 1:
        bits.append("present")
    return " · ".join(bits)


def history_prefix(records: list[dict[str, Any]]) -> str:
    """Stable prefix: preamble + prior acts. Only grows by appending a line."""
    lines = [PREAMBLE]
    lines.extend(format_record(r) for r in records)
    return "\n".join(lines)


def compose_user(records: list[dict[str, Any]], snapshot: str) -> str:
    return history_prefix(records) + "\n\n## This turn\n" + snapshot.rstrip() + "\n"

"""Append-only per-citizen act ledger. Prefix-stable for cache hits."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from adags.gov import as_impeach, as_member_id
from adags.render import as_ballot, collapse_ws

PREAMBLE = (
    "Your own acts and what the host did with them, oldest first. "
    "scratch is a private note to yourself. host: is physics, not debate. "
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
    marked, article = as_impeach(act.get("impeach"))
    if marked:
        rec["impeach"] = article or True
    prop = act.get("propose")
    if isinstance(prop, dict) and (prop.get("title") or prop.get("text") or prop.get("effects")):
        from adags.effects import bill_title, propose_effects

        rec["bill"] = bill_title(
            title=str(prop.get("title") or ""),
            text=str(prop.get("text") or ""),
            effects=prop.get("effects") or propose_effects(prop),
            speech=speech,
        )[:80]
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
    from adags.effects import coerce_effects

    kinds = []
    for fx in coerce_effects(act.get("executive")):
        if isinstance(fx, dict) and fx.get("type"):
            kinds.append(str(fx["type"]))
    for key in ("set_goal", "write_workspace"):
        if act.get(key) is not None:
            kinds.append(key)
    if kinds:
        rec["exec"] = list(dict.fromkeys(kinds))
    scratch = collapse_ws(str(act.get("scratch") or ""))[:160]
    if scratch and scratch.lower() not in {"null", "none", "nil"}:
        rec["scratch"] = scratch
    return rec


def format_record(record: dict[str, Any]) -> str:
    bits = [f"t{record.get('turn', '?')}"]
    if record.get("nominate"):
        bits.append(f"nominated {record['nominate']}")
    if record.get("vote"):
        bits.append(f"voted {record['vote']}")
    if record.get("impeach"):
        charge = record["impeach"]
        bits.append(f"impeach {charge}" if charge is not True else "impeach")
    if record.get("bill"):
        bits.append(f"bill {record['bill']}")
    if record.get("motion"):
        bits.append(record["motion"])
    if record.get("exec"):
        bits.append("exec " + ",".join(record["exec"]))
    if record.get("party"):
        bits.append("party " + str(record["party"]))
    if record.get("scratch"):
        bits.append("scratch " + collapse_ws(str(record["scratch"]))[:120])
    if record.get("host"):
        bits.append("host " + collapse_ws(str(record["host"]))[:180])
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


def patch_last_record(root: Path, member_id: str, turn: int, **fields: Any) -> None:
    """Update this turn's line only. Earlier lines stay byte-stable for the cache."""
    path = memory_file(root, member_id)
    if not path.exists():
        return
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    if not lines:
        return
    try:
        rec = json.loads(lines[-1])
    except json.JSONDecodeError:
        return
    if not isinstance(rec, dict) or int(rec.get("turn") or 0) != int(turn):
        return
    extra_host = fields.pop("host", None)
    rec.update(fields)
    if extra_host:
        prev = collapse_ws(str(rec.get("host") or ""))
        rec["host"] = ((prev + "; " if prev else "") + collapse_ws(str(extra_host)))[:360]
    lines[-1] = json.dumps(rec, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


_UNTIL_TURN = re.compile(r"until\s+turn\s+(\d+)", re.I)
_GOAL_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "your",
        "our",
        "their",
        "until",
        "turn",
        "goal",
        "goals",
        "must",
        "should",
        "will",
        "have",
        "been",
        "each",
        "every",
        "other",
    }
)
GOAL_EVIDENCE_NEED = 3


def goal_until(text: str) -> int | None:
    found = _UNTIL_TURN.search(text or "")
    return int(found.group(1)) if found else None


def _goal_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in re.findall(r"[a-z0-9]{4,}", (text or "").lower())
        if tok not in _GOAL_STOP
    }


def _file_cites_goal(body: str, name: str, gid: str, goal_text: str) -> bool:
    hay = f"{name}\n{body}".lower()
    if gid.lower() in hay:
        return True
    tokens = _goal_tokens(goal_text)
    if not tokens:
        return False
    hits = sum(1 for tok in tokens if tok in hay)
    return hits >= min(2, len(tokens))


def goal_clock(
    goals: dict[str, str],
    workspace: Path,
    turn: int,
    *,
    need: int = GOAL_EVIDENCE_NEED,
) -> str:
    """One line of evidence and due-date for each live goal. Empty if none enacted."""
    if not goals:
        return ""
    files: list[Path] = []
    if workspace.exists():
        files = [p for p in workspace.rglob("*") if p.is_file()]
    bits: list[str] = []
    for gid, text in goals.items():
        cites = 0
        for path in files:
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(workspace).as_posix()
            if _file_cites_goal(body, rel, gid, text):
                cites += 1
        due = goal_until(text)
        if cites >= need:
            state = "complete"
        elif due is not None and int(turn) >= due:
            state = "overdue"
        else:
            state = "open"
        if due is None:
            clock = "no clock"
        else:
            clock = f"due turn {due}"
        bits.append(f"{gid} {state} {min(cites, need)}/{need} files, {clock}")
    return "; ".join(bits)


def workspace_card(workspace: Path, *, limit: int = 8) -> str:
    if not workspace.exists():
        return "(empty)"
    files = sorted(p for p in workspace.rglob("*") if p.is_file())[:limit]
    if not files:
        return "(empty)"
    lines: list[str] = []
    for path in files:
        rel = path.relative_to(workspace).as_posix()
        try:
            head = collapse_ws(path.read_text(encoding="utf-8", errors="replace"))[:80]
        except OSError:
            head = "(unreadable)"
        lines.append(f"- {rel}: {head or '(empty)'}")
    return "\n".join(lines)

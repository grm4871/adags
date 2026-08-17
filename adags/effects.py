"""Whitelist of host effects. Unknown types are inert."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from adags.gov import is_member_id, office, set_param, who_may
from adags.seed import DEFAULT_VALUES

RULE_ID_RE = re.compile(r"^(\d{3})\b")
IMMUTABLE_MIN, IMMUTABLE_MAX = 100, 199
EXECUTIVE_TYPES = frozenset({"write_workspace", "set_goal"})
LEGISLATIVE_OK = frozenset(
    {
        "amend_rule",
        "repeal_rule",
        "set_goal",
        "repeal_goal",
        "add_member",
        "remove_member",
        "set_param",
        "appoint",
        "write_workspace",
        "no_op",
    }
)


def _rule_num(rule_id: str) -> int | None:
    m = RULE_ID_RE.match(str(rule_id).strip())
    return int(m.group(1)) if m else None


def _is_immutable(rule_id: str) -> bool:
    n = _rule_num(rule_id)
    return n is not None and IMMUTABLE_MIN <= n <= IMMUTABLE_MAX


def _safe_relpath(rel: str) -> str | None:
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    return rel.lstrip("./")


def normalize_effect(effect: Any) -> dict | None:
    """Unwrap `{ "amend_rule": {id, text} }` and similar model shapes."""
    if not isinstance(effect, dict):
        return None
    if effect.get("type") in LEGISLATIVE_OK:
        return effect
    nested = [k for k in effect if k in LEGISLATIVE_OK]
    if len(nested) == 1:
        kind = nested[0]
        body = effect[kind]
        if isinstance(body, dict):
            out = {"type": kind, **body}
            if kind == "write_workspace":
                out.setdefault("path", "design-log.md")
                if not str(out.get("content") or "").strip():
                    out["content"] = str(
                        out.get("description")
                        or out.get("text")
                        or out.get("artifact")
                        or out.get("body")
                        or ""
                    )
            if kind == "set_goal" and not out.get("id"):
                out["id"] = "goal1"
            return out
        if kind == "write_workspace":
            return {"type": "write_workspace", "path": "design-log.md", "content": str(body)}
        if kind == "set_goal":
            return {"type": "set_goal", "id": "goal1", "text": str(body)}
        if kind == "repeal_goal":
            return {"type": "repeal_goal", "id": str(body)}
        if kind == "amend_rule":
            return {"type": "amend_rule", "id": "", "text": str(body)}
        if kind in {"add_member", "remove_member"}:
            return {"type": kind, "id": str(body)}
        return {"type": kind, "value": body}
    return effect


def coerce_effects(blob: Any) -> list[dict]:
    """Accept a list, a single effect, or `{write_workspace: "..."}` maps."""
    if blob is None:
        return []
    if isinstance(blob, list):
        out: list[dict] = []
        for item in blob:
            out.extend(coerce_effects(item))
        return out
    if isinstance(blob, dict):
        if blob.get("type") in LEGISLATIVE_OK:
            one = normalize_effect(blob)
            return [one] if one else []
        nested = [k for k in blob if k in LEGISLATIVE_OK]
        if len(nested) > 1:
            out = []
            for key in nested:
                out.extend(coerce_effects({key: blob[key]}))
            return out
        if nested:
            one = normalize_effect(blob)
            return [one] if one else []
    return []


def propose_effects(prop: dict | None) -> list[dict]:
    """Effects from a propose object: `effects` list or keyed type fields."""
    if not isinstance(prop, dict):
        return []
    listed = coerce_effects(prop.get("effects"))
    if listed:
        return listed
    keyed = {
        k: v
        for k, v in prop.items()
        if k in LEGISLATIVE_OK and v not in (None, "", [], {})
    }
    return coerce_effects(keyed) if keyed else []


def salvage_motion_effects(motion: dict) -> list[dict]:
    """Compile common spoken bills the clerk leaves empty."""
    text = f"{motion.get('title') or ''} {motion.get('text') or ''}"
    out: list[dict] = []
    rg = re.search(r"repeal_goal\s+([a-z0-9_-]+)", text, re.I)
    if rg:
        out.append({"type": "repeal_goal", "id": rg.group(1)})
    repl = re.search(
        r"replace(?:e)? with\s+(?:a\s+)?(.+)",
        text,
        re.I | re.S,
    )
    if repl:
        out.append(
            {
                "type": "set_goal",
                "id": "goal1",
                "text": " ".join(repl.group(1).split())[:800],
            }
        )
    am = re.search(
        r"(?:amend(?:_rule)?|constitutional amendment)\s+(?:rule\s+)?(\d{3})?\s*:?\s*(.+)",
        text,
        re.I | re.S,
    )
    if am and not out:
        rid = (am.group(1) or "").strip()
        body = " ".join((am.group(2) or "").split())
        if body:
            fx: dict[str, Any] = {"type": "amend_rule", "text": body[:800]}
            if rid:
                fx["id"] = rid
            out.append(fx)
    return out


def apply_effect(
    effect: dict,
    *,
    constitution: str,
    goals: dict[str, str],
    members: list[dict],
    gov: dict,
    workspace: Path,
    turn: int,
    actor: str | None,
    source: str,
) -> tuple[dict[str, Any], dict | None]:
    """
    Apply one effect. Returns (result, inverse_or_none).
    result: {ok, note, constitution?, goals?, members?, gov?, writes?}
    """
    effect = normalize_effect(effect) or {}
    kind = effect.get("type")
    if kind not in LEGISLATIVE_OK:
        return {"ok": False, "note": f"inert unknown effect {kind!r}"}, None

    if source == "executive" and kind not in EXECUTIVE_TYPES:
        return {"ok": False, "note": f"{kind} is not an executive effect"}, None

    if kind in EXECUTIVE_TYPES and source == "executive":
        holders = who_may(gov, kind, members)
        if holders and actor not in holders:
            return {"ok": False, "note": f"{kind} requires office privilege (holders: {sorted(holders)})"}, None

    if source == "motion" and kind == "appoint" and gov.get("election_enabled") and effect.get("office", "president") == "president":
        return {"ok": False, "note": "appoint president is inert while election_enabled"}, None

    if kind == "no_op":
        return {"ok": True, "note": "no_op"}, None

    if kind == "amend_rule":
        return _amend_rule(effect, constitution)
    if kind == "repeal_rule":
        return _repeal_rule(effect, constitution)
    if kind == "set_goal":
        return _set_goal(effect, goals)
    if kind == "repeal_goal":
        return _repeal_goal(effect, goals)
    if kind == "add_member":
        return _add_member(effect, members, gov)
    if kind == "remove_member":
        return _remove_member(effect, members, gov)
    if kind == "set_param":
        return _set_param(effect, gov, constitution)
    if kind == "appoint":
        return _appoint(effect, members, gov, turn)
    if kind == "write_workspace":
        return _write_workspace(effect, workspace)
    return {"ok": False, "note": f"inert {kind}"}, None


def _amend_rule(effect: dict, constitution: str) -> tuple[dict, dict | None]:
    rid = str(effect.get("id") or "").strip()
    text = str(effect.get("text") or effect.get("value") or "").strip()
    if not rid or _rule_num(rid) is None:
        if not text:
            return {"ok": False, "note": "amend_rule needs numeric id"}, None
        nums = []
        for line in constitution.splitlines():
            m = re.match(r"^(\d{3})\.", line.strip())
            if m:
                nums.append(int(m.group(1)))
        nxt = max([n for n in nums if n >= 200] or [212]) + 1
        rid = f"{nxt:03d}"
    if _is_immutable(rid):
        return {"ok": False, "note": f"cannot amend immutable rule {rid}"}, None
    if not text:
        return {"ok": False, "note": "amend_rule needs text"}, None
    lines = constitution.splitlines()
    pattern = re.compile(rf"^{re.escape(rid)}\.")
    replaced = False
    old = None
    new_lines = []
    for line in lines:
        if pattern.match(line.strip()):
            old = line
            new_lines.append(f"{rid}. {text}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"{rid}. {text}")
        inverse = {"type": "repeal_rule", "id": rid}
    else:
        inverse = {"type": "amend_rule", "id": rid, "text": old.split(". ", 1)[-1] if old else ""}
    return {"ok": True, "note": f"amended {rid}", "constitution": "\n".join(new_lines) + "\n"}, inverse


def _repeal_rule(effect: dict, constitution: str) -> tuple[dict, dict | None]:
    rid = str(effect.get("id") or "").strip()
    if _is_immutable(rid):
        return {"ok": False, "note": f"cannot repeal immutable rule {rid}"}, None
    pattern = re.compile(rf"^{re.escape(rid)}\.")
    old = None
    kept = []
    for line in constitution.splitlines():
        if pattern.match(line.strip()):
            old = line
        else:
            kept.append(line)
    if old is None:
        return {"ok": False, "note": f"no such rule {rid}"}, None
    inverse = {"type": "amend_rule", "id": rid, "text": old.split(". ", 1)[-1]}
    return {"ok": True, "note": f"repealed {rid}", "constitution": "\n".join(kept) + "\n"}, inverse


def _set_goal(effect: dict, goals: dict[str, str]) -> tuple[dict, dict | None]:
    gid = str(effect.get("id") or "g1").strip()
    text = str(effect.get("text") or "").strip()
    if not text:
        return {"ok": False, "note": "set_goal needs text"}, None
    new_goals = deepcopy(goals)
    old = new_goals.get(gid)
    new_goals[gid] = text
    if old is None:
        inverse = {"type": "repeal_goal", "id": gid}
    else:
        inverse = {"type": "set_goal", "id": gid, "text": old}
    return {"ok": True, "note": f"set goal {gid}", "goals": new_goals}, inverse


def _repeal_goal(effect: dict, goals: dict[str, str]) -> tuple[dict, dict | None]:
    gid = str(effect.get("id") or "").strip()
    if gid not in goals:
        return {"ok": False, "note": f"no such goal {gid}"}, None
    new_goals = deepcopy(goals)
    old = new_goals.pop(gid)
    return {"ok": True, "note": f"repealed goal {gid}", "goals": new_goals}, {
        "type": "set_goal",
        "id": gid,
        "text": old,
    }


def _add_member(effect: dict, members: list[dict], gov: dict) -> tuple[dict, dict | None]:
    mid = str(effect.get("id") or "").strip().lower()
    if not is_member_id(mid):
        return {"ok": False, "note": "add_member needs a slug id [a-z][a-z0-9_-]{0,31}"}, None
    if any(m["id"] == mid for m in members):
        return {"ok": False, "note": f"{mid} is already seated"}, None
    cap = gov.get("max_members")
    if cap is not None and len(members) >= int(cap):
        return {"ok": False, "note": f"electorate is at max_members={cap}"}, None
    values = str(effect.get("values") or "").strip()
    if not values or values.startswith("You were seated as "):
        raw = str(effect.get("text") or effect.get("speech") or "")
        grabbed = re.search(
            r"(?:standing\s+)?values?\s*[:\-]\s*(.+)",
            raw,
            re.I | re.S,
        )
        if grabbed:
            values = " ".join(grabbed.group(1).split())[:600]
    if not values:
        values = DEFAULT_VALUES
    new_members = deepcopy(members)
    new_members.append({"id": mid, "values": values})
    return {
        "ok": True,
        "note": f"seated {mid} (acts next turn)",
        "members": new_members,
    }, {"type": "remove_member", "id": mid}


def _remove_member(effect: dict, members: list[dict], gov: dict) -> tuple[dict, dict | None]:
    mid = str(effect.get("id") or "").strip()
    if len(members) <= 1:
        return {"ok": False, "note": "cannot remove the last member"}, None
    if not any(m["id"] == mid for m in members):
        return {"ok": False, "note": f"{mid} is not seated"}, None
    target = next(m for m in members if m["id"] == mid)
    new_members = [m for m in members if m["id"] != mid]
    new_gov = deepcopy(gov)
    off = office(new_gov)
    if off and off.get("holder") == mid:
        new_gov["offices"]["president"]["holder"] = None
        new_gov["offices"]["president"]["term_start"] = None
        new_gov["election_phase"] = "nominate"
        new_gov["nominees"] = []
    return {
        "ok": True,
        "note": f"unseated {mid}",
        "members": new_members,
        "gov": new_gov,
    }, {"type": "add_member", "id": mid, "values": target.get("values", "")}


_PARAM_ALIASES = {
    "max_member": "max_members",
    "term": "term_length",
    "terms": "term_length",
    "term_len": "term_length",
}

_TERM_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}


def normalize_param_key(key: str) -> str:
    text = str(key or "").strip()
    if text.startswith("gov."):
        text = text[4:]
    return _PARAM_ALIASES.get(text, text)


def sync_term_rule(constitution: str, length: int) -> str:
    word = _TERM_WORDS.get(int(length), str(length))
    return re.sub(
        r"Term is (?:\w+|\d+) turns",
        f"Term is {word} turns",
        constitution,
        count=1,
    )


def _set_param(effect: dict, gov: dict, constitution: str = "") -> tuple[dict, dict | None]:
    key = normalize_param_key(str(effect.get("key") or ""))
    value = effect.get("value")
    old = _lookup(gov, key)
    result = set_param(gov, key, value)
    if isinstance(result, str):
        return {"ok": False, "note": result}, None
    out: dict[str, Any] = {"ok": True, "note": f"set {key}", "gov": result}
    if key == "term_length" and constitution:
        updated = sync_term_rule(constitution, int(result["term_length"]))
        if updated != constitution:
            out["constitution"] = updated
    return out, {"type": "set_param", "key": key, "value": old}


def _lookup(gov: dict, key: str) -> Any:
    if key == "offices.president.privileges":
        return (office(gov) or {}).get("privileges")
    return gov.get(key)


def _appoint(effect: dict, members: list[dict], gov: dict, turn: int) -> tuple[dict, dict | None]:
    name = str(effect.get("office") or "president")
    holder = effect.get("holder")
    holder = None if holder in (None, "", "none") else str(holder)
    if holder is not None and not any(m["id"] == holder for m in members):
        return {"ok": False, "note": f"{holder} is not seated"}, None
    new_gov = deepcopy(gov)
    new_gov.setdefault("offices", {}).setdefault(name, {"privileges": [], "holder": None, "term_start": None})
    old_holder = new_gov["offices"][name].get("holder")
    old_start = new_gov["offices"][name].get("term_start")
    new_gov["offices"][name]["holder"] = holder
    new_gov["offices"][name]["term_start"] = turn
    return {"ok": True, "note": f"appointed {holder} as {name}", "gov": new_gov}, {
        "type": "appoint",
        "office": name,
        "holder": old_holder,
        "term_start": old_start,
    }


def _write_workspace(effect: dict, workspace: Path) -> tuple[dict, dict | None]:
    rel = _safe_relpath(str(effect.get("path") or "design-log.md"))
    if not rel:
        return {"ok": False, "note": "write_workspace needs a safe relative path"}, None
    content = str(effect.get("content") or effect.get("text") or effect.get("description") or "")
    dest = (workspace / rel).resolve()
    try:
        dest.relative_to(workspace.resolve())
    except ValueError:
        return {"ok": False, "note": "path escapes workspace"}, None
    dest.parent.mkdir(parents=True, exist_ok=True)
    old = dest.read_text(encoding="utf-8") if dest.exists() else None
    dest.write_text(content, encoding="utf-8")
    if old is None:
        inverse = {"type": "_delete_workspace", "path": rel}
    else:
        inverse = {"type": "write_workspace", "path": rel, "content": old}
    return {
        "ok": True,
        "note": f"wrote workspace/{rel}",
        "writes": [rel],
    }, inverse


def apply_inverse(inverse: dict, *, workspace: Path, **kwargs) -> dict:
    if inverse.get("type") == "_delete_workspace":
        rel = _safe_relpath(str(inverse.get("path") or ""))
        if not rel:
            return {"ok": False, "note": "bad inverse path"}
        dest = workspace / rel
        if dest.exists():
            dest.unlink()
        return {"ok": True, "note": f"deleted workspace/{rel}"}
    result, _ = apply_effect(inverse, workspace=workspace, actor=None, source="veto", **kwargs)
    return result


def render_goals(goals: dict[str, str]) -> str:
    if not goals:
        return "# Goals\n\n(none enacted)\n"
    lines = ["# Goals", ""]
    for gid, text in goals.items():
        lines.append(f"## {gid}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def parse_goals(text: str) -> dict[str, str]:
    goals: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                goals[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        elif current is not None:
            if line.strip() == "(none enacted)":
                continue
            buf.append(line)
    if current:
        goals[current] = "\n".join(buf).strip()
    return {k: v for k, v in goals.items() if v}

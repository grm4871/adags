"""Whitelist of host effects. Unknown types are inert."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from adags.constitution import validate_patch, value
from adags.gov import is_member_id, office
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
        "appoint",
        "write_workspace",
        "suggest_host_change",
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
        out = dict(effect)
        if out["type"] == "amend_rule":
            if not out.get("id") and out.get("rule_id") is not None:
                out["id"] = str(out["rule_id"])
            if not out.get("text") and out.get("new_text") is not None:
                out["text"] = str(out["new_text"])
        return out
    nested = [k for k in effect if k in LEGISLATIVE_OK]
    if len(nested) == 1:
        kind = nested[0]
        body = effect[kind]
        if isinstance(body, dict):
            out = {"type": kind, **body}
            if kind == "amend_rule":
                if not out.get("id") and out.get("rule_id") is not None:
                    out["id"] = str(out["rule_id"])
                if not out.get("text") and out.get("new_text") is not None:
                    out["text"] = str(out["new_text"])
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


def apply_effect(
    effect: dict,
    *,
    law: dict,
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
    result: {ok, note, law?, goals?, members?, gov?, writes?}
    """
    effect = normalize_effect(effect) or {}
    kind = effect.get("type")
    if kind not in LEGISLATIVE_OK:
        return {"ok": False, "note": f"inert unknown effect {kind!r}"}, None

    if source == "executive" and kind not in EXECUTIVE_TYPES:
        return {"ok": False, "note": f"{kind} is not an executive effect"}, None

    if kind in EXECUTIVE_TYPES:
        holder = (office(gov) or {}).get("holder")
        privileges = value(law, "offices.president.privileges", [])
        holders = {holder} if holder and kind in privileges else set()
        if source == "executive" and actor not in holders:
            return {"ok": False, "note": f"{kind} requires office privilege (holders: {sorted(holders)})"}, None
        if source == "motion" and kind in privileges:
            return {"ok": False, "note": f"{kind} is reserved to the President"}, None

    if source == "motion" and kind == "appoint" and value(law, "election.enabled", True) and effect.get("office", "president") == "president":
        return {"ok": False, "note": "appoint president is inert while election_enabled"}, None

    if kind == "no_op":
        return {"ok": True, "note": "no_op"}, None

    if kind == "amend_rule":
        return _amend_rule(effect, law)
    if kind == "repeal_rule":
        return _repeal_rule(effect, law)
    if kind == "set_goal":
        return _set_goal(effect, goals)
    if kind == "repeal_goal":
        return _repeal_goal(effect, goals)
    if kind == "add_member":
        return _add_member(effect, members, law)
    if kind == "remove_member":
        return _remove_member(effect, members, gov)
    if kind == "appoint":
        return _appoint(effect, members, gov, turn)
    if kind == "write_workspace":
        return _write_workspace(effect, workspace)
    if kind == "suggest_host_change":
        return _suggest_host_change(effect, workspace, turn, actor)
    return {"ok": False, "note": f"inert {kind}"}, None


def _amend_rule(effect: dict, law: dict) -> tuple[dict, dict | None]:
    rid = str(effect.get("id") or "").strip()
    text = str(effect.get("text") or effect.get("value") or "").strip()
    number = _rule_num(rid) if rid else None
    if number is None or number < 200:
        return {"ok": False, "note": "amend_rule needs a 200-series numeric rule id"}, None
    if _is_immutable(rid):
        return {"ok": False, "note": f"cannot amend immutable rule {rid}"}, None
    mechanics = effect.get("mechanics")
    problem = validate_patch(mechanics)
    if problem:
        return {"ok": False, "note": problem}, None
    if not text:
        return {"ok": False, "note": "amend_rule needs human-readable text"}, None
    new_law = deepcopy(law)
    old = deepcopy((new_law.get("rules") or {}).get(rid))
    merged = deepcopy((old or {}).get("mechanics") or {})
    merged.update(mechanics)
    new_law.setdefault("rules", {})[rid] = {"text": text, "mechanics": merged}
    inverse = {"type": "_restore_rule", "id": rid, "rule": old}
    return {"ok": True, "note": f"amended executable rule {rid}", "law": new_law}, inverse


def _repeal_rule(effect: dict, law: dict) -> tuple[dict, dict | None]:
    rid = str(effect.get("id") or "").strip()
    if _is_immutable(rid):
        return {"ok": False, "note": f"cannot repeal immutable rule {rid}"}, None
    old = deepcopy((law.get("rules") or {}).get(rid))
    if old is None:
        return {"ok": False, "note": f"no such rule {rid}"}, None
    if old.get("mechanics"):
        return {"ok": False, "note": f"rule {rid} has executable mechanics; amend or disable it instead"}, None
    new_law = deepcopy(law)
    del new_law["rules"][rid]
    return {"ok": True, "note": f"repealed resolution {rid}", "law": new_law}, {
        "type": "_restore_rule", "id": rid, "rule": old
    }


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


def _add_member(effect: dict, members: list[dict], law: dict) -> tuple[dict, dict | None]:
    mid = str(effect.get("id") or "").strip().lower()
    if not is_member_id(mid):
        return {"ok": False, "note": "add_member needs a slug id [a-z][a-z0-9_-]{0,31}"}, None
    if any(m["id"] == mid for m in members):
        return {"ok": False, "note": f"{mid} is already seated"}, None
    cap = value(law, "membership.max_members")
    if cap is not None and len(members) >= int(cap):
        return {"ok": False, "note": f"electorate is at max_members={cap}"}, None
    values = str(effect.get("values") or "").strip()
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


def _appoint(effect: dict, members: list[dict], gov: dict, turn: int) -> tuple[dict, dict | None]:
    name = str(effect.get("office") or "president")
    holder = effect.get("holder")
    holder = None if holder in (None, "", "none") else str(holder)
    if holder is not None and not any(m["id"] == holder for m in members):
        return {"ok": False, "note": f"{holder} is not seated"}, None
    new_gov = deepcopy(gov)
    new_gov.setdefault("offices", {}).setdefault(name, {"holder": None, "term_start": None})
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


def _suggest_host_change(
    effect: dict, workspace: Path, turn: int, actor: str | None
) -> tuple[dict, dict | None]:
    title = str(effect.get("title") or "Host suggestion").strip()[:120]
    text = str(effect.get("text") or effect.get("description") or "").strip()
    if not text:
        return {"ok": False, "note": "suggest_host_change needs text"}, None
    box = workspace.parent / "suggestions"
    box.mkdir(exist_ok=True)
    stem = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "suggestion"
    rel = f"t{turn}-{actor or 'chamber'}-{stem}.md"
    dest = box / rel
    suffix = 2
    while dest.exists():
        dest = box / f"t{turn}-{actor or 'chamber'}-{stem}-{suffix}.md"
        suffix += 1
    dest.write_text(
        f"# {title}\n\nFrom: {actor or 'chamber'}\nTurn: {turn}\nStatus: pending host review\n\n{text}\n",
        encoding="utf-8",
    )
    return {"ok": True, "note": f"filed host suggestion {dest.name}"}, {
        "type": "_delete_suggestion", "path": dest.name
    }


def apply_inverse(inverse: dict, *, workspace: Path, **kwargs) -> dict:
    if inverse.get("type") == "_delete_workspace":
        rel = _safe_relpath(str(inverse.get("path") or ""))
        if not rel:
            return {"ok": False, "note": "bad inverse path"}
        dest = workspace / rel
        if dest.exists():
            dest.unlink()
        return {"ok": True, "note": f"deleted workspace/{rel}"}
    if inverse.get("type") == "_delete_suggestion":
        name = Path(str(inverse.get("path") or "")).name
        dest = workspace.parent / "suggestions" / name
        if dest.exists():
            dest.unlink()
        return {"ok": True, "note": f"deleted suggestion/{name}"}
    if inverse.get("type") == "_restore_rule":
        law = deepcopy(kwargs["law"])
        rid = str(inverse.get("id") or "")
        rule = inverse.get("rule")
        if rule is None:
            law.get("rules", {}).pop(rid, None)
        else:
            law.setdefault("rules", {})[rid] = deepcopy(rule)
        return {"ok": True, "note": f"restored rule {rid}", "law": law}
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

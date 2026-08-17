"""Whitelist of host effects. Unknown types are inert."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from adags.constitution import (
    CHAMBER_MIN,
    canonicalize_patch,
    ensure_charter,
    matching_article,
    next_charter_id,
    validate_patch,
    value,
)
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


_PATHISH = re.compile(r"^[a-z0-9][a-z0-9_./-]*\.[a-z0-9]{1,8}$", re.I)
_EMBEDDED_PATH = re.compile(
    r"(?:workspace/)?((?:[a-z0-9_-]+/)*[a-z0-9_-]+\.[a-z0-9]{1,8})",
    re.I,
)
_GOAL_LABEL = re.compile(
    r"^(?P<id>goal[-_]?\d+|g\d+)\s*[:.\u2014\u2013-]\s*(?P<text>.+)$",
    re.I | re.S,
)
_GOAL_ID_ONLY = re.compile(r"^(?:goal[-_]?|g)(\d+)$", re.I)


def _safe_relpath(rel: str) -> str | None:
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    return rel.lstrip("./")


def _as_workspace_rel(raw: str) -> str | None:
    text = str(raw or "").strip().lstrip("./")
    while text.lower().startswith("workspace/"):
        text = text.split("/", 1)[1]
    if not _PATHISH.match(text):
        return None
    if ".." in Path(text).parts or text.startswith("/"):
        return None
    return text


def path_in_prose(raw: str) -> str | None:
    """First workspace-relative file mentioned in a sentence."""
    for match in _EMBEDDED_PATH.finditer(raw or ""):
        rel = _as_workspace_rel(match.group(1))
        if rel:
            return rel
    return None


def _canon_goal_id(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    found = _GOAL_ID_ONLY.match(text)
    if found:
        return f"goal{int(found.group(1))}"
    if re.fullmatch(r"g\d+", text, re.I):
        return f"goal{int(text[1:])}"
    return None


def complete_set_goal(effect: dict, speech: str = "") -> dict:
    """Honor goal3/goal4 as ids. Speech fills text when the field is only an id."""
    explicit = str(effect.get("id") or "").strip()
    raw = str(
        effect.get("text") or effect.get("value") or effect.get("goal") or ""
    ).strip()
    gid = explicit
    text = raw
    labeled = _GOAL_LABEL.match(raw)
    if labeled:
        if not gid:
            gid = _canon_goal_id(labeled.group("id")) or labeled.group("id").lower()
        text = labeled.group("text").strip()
    elif not gid and _canon_goal_id(raw):
        gid = _canon_goal_id(raw) or ""
        text = ""
    if not text and speech:
        spoken = re.search(
            r"(?:set|enact|establish|declare)\s+(?:the\s+|a\s+|our\s+)?"
            r"(?P<id>goal[-_]?\d+|g\d+|goal)\b\s*[:.\u2014\u2013-]?\s*(?P<body>.+)",
            speech,
            re.I | re.S,
        )
        if spoken:
            spoken_id = _canon_goal_id(spoken.group("id"))
            if spoken_id and not gid:
                gid = spoken_id
            body = spoken.group("body").strip()
            labeled = _GOAL_LABEL.match(body)
            if labeled:
                if not gid:
                    gid = _canon_goal_id(labeled.group("id")) or labeled.group("id").lower()
                text = labeled.group("text").strip()
            elif not _canon_goal_id(body):
                text = body
        if not text and gid:
            tail = re.search(
                rf"{re.escape(gid)}\s*[:.\u2014\u2013-]\s*(.+)",
                speech,
                re.I | re.S,
            )
            if tail:
                text = tail.group(1).strip()
    effect["id"] = gid or "goal1"
    effect["text"] = " ".join(text.split()) if text else ""
    return effect


def _resolve_write_fields(effect: dict) -> dict:
    """Prefer a named .md path over defaulting everything to design-log.md."""
    path = str(effect.get("path") or "").strip()
    named = _as_workspace_rel(path)
    if not named:
        for key in ("artifact", "file", "filename"):
            named = _as_workspace_rel(str(effect.get(key) or ""))
            if named:
                break
    content = str(
        effect.get("content")
        or effect.get("text")
        or effect.get("description")
        or effect.get("body")
        or ""
    ).strip()
    content_path = _as_workspace_rel(content)
    if content_path and (not named or named == "design-log.md"):
        named = content_path
        content = ""
    elif not named or named == "design-log.md":
        embedded = path_in_prose(content)
        if embedded:
            named = embedded
    effect["path"] = named or "design-log.md"
    effect["content"] = content
    return effect


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
        if out["type"] == "write_workspace":
            _resolve_write_fields(out)
        if out["type"] == "set_goal":
            complete_set_goal(out)
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
                _resolve_write_fields(out)
            if kind == "set_goal":
                complete_set_goal(out)
            return out
        if kind == "write_workspace":
            return _resolve_write_fields({"type": "write_workspace", "content": str(body)})
        if kind == "set_goal":
            return complete_set_goal({"type": "set_goal", "text": str(body)})
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


def bill_title(
    *,
    title: str = "",
    text: str = "",
    effects: list | None = None,
    speech: str = "",
) -> str:
    """Human label for the operator view. Never prefer the word untitled."""
    raw = re.sub(r"\s+", " ", str(title or "")).strip()
    if raw and raw.lower() != "untitled":
        return raw[:120]
    for fx in effects or []:
        if not isinstance(fx, dict):
            continue
        kind = str(fx.get("type") or "")
        if not kind:
            nested = [k for k in fx if k in LEGISLATIVE_OK]
            kind = nested[0] if len(nested) == 1 else ""
        if kind == "add_member" and fx.get("id"):
            return f"Admit {fx['id']}"
        if kind == "remove_member" and fx.get("id"):
            return f"Unseat {fx['id']}"
        if kind == "amend_rule":
            rid = str(fx.get("id") or "").strip()
            body = re.sub(r"\s+", " ", str(fx.get("text") or "")).strip()
            if rid and body:
                return f"amend {rid}: {body}"[:120]
            if rid:
                return f"amend {rid}"
            if body:
                return f"amend: {body}"[:120]
            return "amend_rule"
        if kind == "repeal_rule" and fx.get("id"):
            return f"repeal {fx['id']}"
        if kind == "repeal_goal" and fx.get("id"):
            return f"repeal_goal {fx['id']}"
        if kind == "set_goal":
            return f"set_goal {(fx.get('text') or fx.get('id') or '')}".strip()[:120]
        if kind == "set_param" and fx.get("key"):
            return f"set_param {fx['key']}"
        if kind == "write_workspace":
            return f"write {fx.get('path') or 'workspace'}"
        if kind == "suggest_host_change":
            return f"suggest {fx.get('title') or 'host change'}"[:120]
        if kind:
            extra = fx.get("id") or fx.get("path") or ""
            return f"{kind} {extra}".strip()[:120]
    for src in (text, speech):
        body = re.sub(r"\s+", " ", str(src or "")).strip()
        if not body:
            continue
        first = re.split(r"[.!\n]", body, maxsplit=1)[0].strip()
        if first:
            return first[:120]
    return "untitled"


def propose_effects(prop: dict | None) -> list[dict]:
    """Effects from a propose object: `effects` list, keyed types, or a bare effect."""
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
    if keyed:
        return coerce_effects(keyed)
    if prop.get("type") in LEGISLATIVE_OK:
        return coerce_effects(prop)
    return []


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
        if source == "motion" and kind in privileges and not value(law, "offices.president.override"):
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
        return _set_goal(effect, goals, law)
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
    if not text:
        return {"ok": False, "note": "amend_rule needs human-readable text"}, None
    number = _rule_num(rid) if rid else None
    if rid and _is_immutable(rid):
        return {"ok": False, "note": f"cannot amend immutable rule {rid}"}, None
    law = ensure_charter(law)
    if rid and number is None:
        return {
            "ok": False,
            "note": "amend_rule needs a numeric id, or omit id to append the next chamber article",
        }, None
    mechanics = effect.get("mechanics") if isinstance(effect.get("mechanics"), dict) else None
    has_mechanics = bool(mechanics)
    host_ok = has_mechanics and validate_patch(mechanics) is None
    host_rule = rid in (law.get("rules") or {})
    if number is not None and number >= CHAMBER_MIN:
        return _write_charter(law, rid, text)
    if not has_mechanics:
        if host_rule:
            return _relabel_host_rule(law, rid, text)
        rid = rid if number and number >= 200 else next_charter_id(law)
        if number is not None and 200 <= number < CHAMBER_MIN:
            rid = next_charter_id(law)
        return _write_charter(law, rid, text)
    if host_ok and not (number is not None and number >= CHAMBER_MIN):
        if number is None:
            return {"ok": False, "note": "host knobs need a 200-series rule id"}, None
        # fall through to host amend below
    elif not host_ok:
        if host_rule:
            return {"ok": False, "note": validate_patch(mechanics)}, None
        return _write_charter(law, next_charter_id(law), text)
    new_law = deepcopy(law)
    old = deepcopy((new_law.get("rules") or {}).get(rid))
    merged = deepcopy((old or {}).get("mechanics") or {})
    merged.update(canonicalize_patch(mechanics))
    new_law.setdefault("rules", {})[rid] = {"text": text, "mechanics": merged}
    inverse = {"type": "_restore_rule", "id": rid, "rule": old}
    return {"ok": True, "note": f"amended host rule {rid}", "law": new_law}, inverse


def _relabel_host_rule(law: dict, rid: str, text: str, extra: str | None = None) -> tuple[dict, dict | None]:
    new_law = deepcopy(law)
    old = deepcopy((new_law.get("rules") or {}).get(rid))
    if old is None:
        return {"ok": False, "note": f"no such host rule {rid}"}, None
    new_law["rules"][rid] = {"text": text, "mechanics": deepcopy(old.get("mechanics") or {})}
    note = f"updated wording of host rule {rid}; knobs unchanged"
    if extra:
        note = f"{note} ({extra})"
    return {"ok": True, "note": note, "law": new_law}, {
        "type": "_restore_rule",
        "id": rid,
        "rule": old,
    }


def _write_charter(law: dict, rid: str, text: str) -> tuple[dict, dict | None]:
    match = matching_article(law, text)
    if match:
        return {
            "ok": True,
            "note": f"already law {match} (identical text; no new article)",
            "law": law,
        }, None
    new_law = deepcopy(law)
    new_law.setdefault("charter", {})
    old = deepcopy(new_law["charter"].get(rid))
    new_law["charter"][rid] = {"text": text}
    verb = "amended" if old else "enacted"
    return {
        "ok": True,
        "note": f"{verb} chamber law {rid} (members enforce; host does not)",
        "law": new_law,
    }, {"type": "_restore_charter", "id": rid, "article": old}


def _repeal_rule(effect: dict, law: dict) -> tuple[dict, dict | None]:
    rid = str(effect.get("id") or "").strip()
    if _is_immutable(rid):
        return {"ok": False, "note": f"cannot repeal immutable rule {rid}"}, None
    law = ensure_charter(law)
    if rid in (law.get("charter") or {}):
        new_law = deepcopy(law)
        old = new_law["charter"].pop(rid)
        return {"ok": True, "note": f"repealed chamber law {rid}", "law": new_law}, {
            "type": "_restore_charter",
            "id": rid,
            "article": old,
        }
    old = deepcopy((law.get("rules") or {}).get(rid))
    if old is None:
        return {"ok": False, "note": f"no such rule {rid}"}, None
    if old.get("mechanics"):
        return {"ok": False, "note": f"rule {rid} has host knobs; amend or disable it instead"}, None
    new_law = deepcopy(law)
    del new_law["rules"][rid]
    return {"ok": True, "note": f"repealed host resolution {rid}", "law": new_law}, {
        "type": "_restore_rule", "id": rid, "rule": old
    }


def _set_goal(effect: dict, goals: dict[str, str], law: dict) -> tuple[dict, dict | None]:
    gid = str(effect.get("id") or "g1").strip()
    text = str(effect.get("text") or "").strip()
    if not text:
        return {"ok": False, "note": "set_goal needs text"}, None
    cap = value(law, "goals.max_live", 3)
    if gid not in goals and cap is not None and len(goals) >= int(cap):
        return {
            "ok": False,
            "note": f"goal register full ({int(cap)}); repeal_goal one first",
        }, None
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
    effect = _resolve_write_fields(dict(effect))
    rel = _safe_relpath(str(effect.get("path") or "design-log.md"))
    if not rel:
        return {"ok": False, "note": "write_workspace needs a safe relative path"}, None
    content = str(effect.get("content") or effect.get("text") or effect.get("description") or "")
    body = content.strip()
    if not body or body == rel or _as_workspace_rel(body) == rel:
        return {"ok": False, "note": f"wrote nothing ({rel} empty or path-only)"}, None
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
    if inverse.get("type") == "_restore_charter":
        law = deepcopy(kwargs["law"])
        rid = str(inverse.get("id") or "")
        article = inverse.get("article")
        law.setdefault("charter", {})
        if article is None:
            law["charter"].pop(rid, None)
        else:
            law["charter"][rid] = deepcopy(article)
        return {"ok": True, "note": f"restored chamber law {rid}", "law": law}
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

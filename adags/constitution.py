"""Executable interior law and its human-readable rendering."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

HARD_RULES = {
    "101": "The host enforces this series. Interior law cannot amend it.",
    "102": "The operator may pause the run at any time.",
    "103": "The operator may veto any act and reverse reversible effects.",
    "104": "The run stops at its budget, turn, or wall-clock limit.",
    "105": "Only whitelisted effects execute; other text is speech.",
    "106": "Speech, motions, votes, clerk output, and effects are journaled.",
    "107": "There is always at least one member.",
}

DEFAULT_RULES = {
    "201": {
        "text": "A motion passes by a simple majority of seated members.",
        "mechanics": {"motion.threshold": "majority"},
    },
    "202": {
        "text": "Any member may propose when the docket is empty or vote on the open motion.",
        "mechanics": {"motion.eligible_proposers": "all_members", "motion.eligible_voters": "all_members"},
    },
    "203": {
        "text": "There is at most one open motion at a time.",
        "mechanics": {"motion.max_open": 1},
    },
    "204": {
        "text": "A passed motion executes only validated structured host effects.",
        "mechanics": {"motion.resolve_when": "decisive"},
    },
    "205": {
        "text": "The goal register holds at most three live objectives; a fourth requires repealing one.",
        "mechanics": {"goals.max_live": 3},
    },
    "206": {"text": "Interior rules may be amended only with executable mechanics accepted by the host.", "mechanics": {}},
    "207": {
        "text": (
            "The President alone may write the workspace as an executive act. "
            "The floor may set and repeal goals by motion. "
            "A published override threshold may let the floor write the workspace by motion."
        ),
        "mechanics": {"offices.president.privileges": ["write_workspace", "set_goal"]},
    },
    "208": {
        "text": (
            "The President is elected by plurality for eight turns and may not "
            "succeed themselves; earliest nomination breaks ties."
        ),
        "mechanics": {
            "election.enabled": True,
            "election.method": "plurality",
            "election.tie_break": "earliest_nomination",
            "election.quorum": "majority",
            "election.term_length": 8,
            "election.consecutive_limit": 1,
        },
    },
    "209": {
        "text": "A majority of seated members may impeach the President in one turn.",
        "mechanics": {"impeachment.enabled": True, "impeachment.threshold": "majority"},
    },
    "210": {
        "text": (
            "Any seated member may be nominated, including themselves, except the "
            "sitting President, who may not seek a consecutive term."
        ),
        "mechanics": {},
    },
    "211": {
        "text": "Membership is open unless the polity enacts a numerical cap.",
        "mechanics": {"membership.max_members": None},
    },
    "212": {"text": "At founding the presidency is vacant and the first business is an election.", "mechanics": {}},
}

MECHANIC_SPECS: dict[str, tuple[type | tuple[type, ...], Any]] = {
    "motion.threshold": (str, {"majority", "two_thirds", "unanimous"}),
    "motion.eligible_proposers": (str, {"all_members"}),
    "motion.eligible_voters": (str, {"all_members"}),
    "motion.max_open": (int, {1}),
    "motion.resolve_when": (str, {"decisive", "all_voted"}),
    "election.enabled": (bool, None),
    "election.method": (str, {"plurality"}),
    "election.tie_break": (str, {"earliest_nomination"}),
    "election.quorum": (str, {"majority", "two_thirds", "unanimous"}),
    "election.term_length": (int, range(1, 101)),
    "election.consecutive_limit": ((int, type(None)), range(0, 11)),
    "goals.max_live": ((int, type(None)), range(1, 21)),
    "impeachment.enabled": (bool, None),
    "impeachment.threshold": (str, {"majority", "two_thirds", "unanimous"}),
    "membership.max_members": ((int, type(None)), None),
    "offices.president.privileges": (list, None),
    "offices.president.override": ((str, type(None)), {"majority", "two_thirds", "unanimous"}),
}

MECHANIC_ALIASES = {
    "executive.override.threshold": "offices.president.override",
    "motion.override_president_executive": "offices.president.override",
    "offices.president.override.threshold": "offices.president.override",
    "president.override": "offices.president.override",
}

VALUE_ALIASES = {
    "supermajority": "two_thirds",
    "super-majority": "two_thirds",
    "super_majority": "two_thirds",
    "2/3": "two_thirds",
}


CHAMBER_MIN = 300

DEFAULT_CHARTER = {
    "301": {
        "text": (
            "This is a digital nation of language-model constituents. "
            "The chamber's charge is to govern and grow it: contest office, "
            "keep a goal the next President can fail, file proof of work, "
            "and seat another member when the work needs another voice. "
            "Members enforce this series by speech, vote, impeachment, and office. "
            "The host does not execute these articles."
        )
    }
}


def default_constitution() -> dict:
    return {
        "version": 2,
        "rules": deepcopy(DEFAULT_RULES),
        "charter": deepcopy(DEFAULT_CHARTER),
    }


def next_charter_id(law: dict) -> str:
    nums = [int(k) for k in (law.get("charter") or {}) if str(k).isdigit()]
    nxt = max([CHAMBER_MIN - 1, *nums]) + 1
    return f"{nxt:03d}"


def ensure_charter(law: dict) -> dict:
    out = deepcopy(law)
    if not out.get("charter"):
        out["charter"] = deepcopy(DEFAULT_CHARTER)
    return out


def norm_article_text(text: str) -> str:
    return " ".join(str(text or "").split())


def matching_article(law: dict, text: str) -> str | None:
    """Lowest id whose wording matches after whitespace normalize."""
    want = norm_article_text(text)
    if not want:
        return None
    items: list[tuple[int, str, str]] = []
    for rid, article in (law.get("charter") or {}).items():
        body = article.get("text", article) if isinstance(article, dict) else str(article)
        items.append((int(rid) if str(rid).isdigit() else 10**9, str(rid), body))
    for rid, rule in (law.get("rules") or {}).items():
        items.append((int(rid) if str(rid).isdigit() else 10**9, str(rid), str((rule or {}).get("text") or "")))
    for _n, rid, body in sorted(items, key=lambda row: row[0]):
        if norm_article_text(body) == want:
            return rid
    return None


def identical_charter_line(law: dict) -> str:
    """Fact line: '302 = 304 = 305 (identical text)'. Empty if none."""
    buckets: dict[str, list[str]] = {}
    for rid, article in (law.get("charter") or {}).items():
        body = article.get("text", article) if isinstance(article, dict) else str(article)
        key = norm_article_text(body)
        if key:
            buckets.setdefault(key, []).append(str(rid))
    groups = []
    for ids in buckets.values():
        if len(ids) < 2:
            continue
        ids.sort(key=lambda x: int(x) if x.isdigit() else x)
        groups.append(" = ".join(ids))
    if not groups:
        return ""
    groups.sort()
    return "; ".join(groups) + " (identical text)"


def mechanics(law: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rules = law.get("rules") or {}
    # Later numbered law overrides earlier law using the same published mechanic.
    for rid in sorted(rules, key=int):
        rule = rules[rid]
        out.update(rule.get("mechanics") or {})
    return out


def value(law: dict, path: str, default: Any = None) -> Any:
    return mechanics(law).get(path, default)


def apply_to_runtime(gov: dict, law: dict) -> dict:
    """Overlay canonical law onto transient election/office state."""
    out = deepcopy(gov)
    out["vote_rule"] = value(law, "motion.threshold", "majority")
    out["election_rule"] = value(law, "election.method", "plurality")
    out["term_length"] = value(law, "election.term_length", 8)
    out["consecutive_limit"] = value(law, "election.consecutive_limit", 1)
    out["impeach_threshold"] = value(law, "impeachment.threshold", "majority")
    out["election_enabled"] = value(law, "election.enabled", True)
    out["max_members"] = value(law, "membership.max_members")
    return out


def canonicalize_patch(patch: dict) -> dict:
    """Rewrite aliases agents already emit onto published paths and values."""
    out: dict[str, Any] = {}
    for raw_path, val in (patch or {}).items():
        path = MECHANIC_ALIASES.get(str(raw_path), str(raw_path))
        if isinstance(val, str):
            key = val.strip().lower().replace(" ", "_")
            val = VALUE_ALIASES.get(key, val)
            if val == "none":
                val = None
        out[path] = val
    return out


def published_paths() -> str:
    return ", ".join(sorted(MECHANIC_SPECS))


def validate_patch(patch: dict) -> str | None:
    if not isinstance(patch, dict) or not patch:
        return "amend_rule needs a non-empty mechanics object"
    patch = canonicalize_patch(patch)
    for path, val in patch.items():
        spec = MECHANIC_SPECS.get(path)
        if not spec:
            if str(path).startswith("workspace."):
                return (
                    f"unsupported mechanic {path} — no workspace.* path is published; "
                    "use suggest_host_change"
                )
            if "override" in str(path) or str(path).startswith("executive."):
                return (
                    f"unsupported mechanic {path} — 207 knobs are "
                    "offices.president.privileges and offices.president.override "
                    "(majority|two_thirds|unanimous; supermajority=two_thirds)"
                )
            return (
                f"unsupported mechanic {path}. published: {published_paths()}. "
                "use suggest_host_change for anything else"
            )
        expected, allowed = spec
        if not isinstance(val, expected) or isinstance(val, bool) and expected is int:
            return f"invalid value for {path}"
        if path == "membership.max_members" and val is not None and val < 1:
            return "membership.max_members must be null or >= 1"
        if path == "offices.president.privileges" and (
            not all(isinstance(x, str) for x in val)
            or any(x not in {"write_workspace", "set_goal"} for x in val)
        ):
            return "unsupported presidential privilege"
        if allowed is not None and val is not None and val not in allowed:
            return f"unsupported value for {path} (want {sorted(allowed) if not isinstance(allowed, range) else 'int'})"
    return None


def render(law: dict) -> str:
    lines = [
        "# Constitution of the run",
        "",
        "## Chamber law — enforced by members",
        "",
        "The host does not execute this series. Cite it, vote it, impeach for it.",
        "",
    ]
    charter = law.get("charter") or {}
    if charter:
        for rid, article in sorted(charter.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
            text = article.get("text", article) if isinstance(article, dict) else str(article)
            lines.append(f"{rid}. {text}")
    else:
        lines.append("(none yet — amend_rule 300+ to write one)")
    lines.extend(
        [
            "",
            "## Host law — enforced by the program",
            "",
            "### 100-series — immutable",
            "",
        ]
    )
    lines.extend(f"{rid}. {text}" for rid, text in HARD_RULES.items())
    lines.extend(["", "### 200-series — mutable knobs", ""])
    for rid, rule in sorted((law.get("rules") or {}).items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
        lines.append(f"{rid}. {rule.get('text', '')}")
        for path, val in (rule.get("mechanics") or {}).items():
            lines.append(f"    - `{path}` = `{val}`")
    lines.extend(
        [
            "",
            "Published host knobs: " + published_paths() + ".",
            "Aliases: supermajority = two_thirds; "
            "executive.override.threshold = offices.president.override.",
            "A sentence without a published knob is chamber law, not host physics.",
        ]
    )
    return "\n".join(lines) + "\n"

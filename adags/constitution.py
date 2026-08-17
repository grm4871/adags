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
    "205": {"text": "The goal register contains the polity's current objectives.", "mechanics": {}},
    "206": {"text": "Interior rules may be amended only with executable mechanics accepted by the host.", "mechanics": {}},
    "207": {
        "text": "The President alone may write the workspace and set goals as executive acts.",
        "mechanics": {"offices.president.privileges": ["write_workspace", "set_goal"]},
    },
    "208": {
        "text": "The President is elected by plurality for four turns; earliest nomination breaks ties.",
        "mechanics": {
            "election.enabled": True,
            "election.method": "plurality",
            "election.tie_break": "earliest_nomination",
            "election.quorum": "majority",
            "election.term_length": 4,
        },
    },
    "209": {
        "text": "A majority of seated members may impeach the President in one turn.",
        "mechanics": {"impeachment.enabled": True, "impeachment.threshold": "majority"},
    },
    "210": {"text": "Any member may nominate any seated member, including themselves.", "mechanics": {}},
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
    "impeachment.enabled": (bool, None),
    "impeachment.threshold": (str, {"majority", "two_thirds", "unanimous"}),
    "membership.max_members": ((int, type(None)), None),
    "offices.president.privileges": (list, None),
}


def default_constitution() -> dict:
    return {"version": 1, "rules": deepcopy(DEFAULT_RULES)}


def mechanics(law: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rule in (law.get("rules") or {}).values():
        out.update(rule.get("mechanics") or {})
    return out


def value(law: dict, path: str, default: Any = None) -> Any:
    return mechanics(law).get(path, default)


def apply_to_runtime(gov: dict, law: dict) -> dict:
    """Overlay canonical law onto transient election/office state."""
    out = deepcopy(gov)
    out["vote_rule"] = value(law, "motion.threshold", "majority")
    out["election_rule"] = value(law, "election.method", "plurality")
    out["term_length"] = value(law, "election.term_length", 4)
    out["impeach_threshold"] = value(law, "impeachment.threshold", "majority")
    out["election_enabled"] = value(law, "election.enabled", True)
    out["max_members"] = value(law, "membership.max_members")
    out.setdefault("offices", {}).setdefault("president", {})["privileges"] = value(
        law, "offices.president.privileges", []
    )
    return out


def validate_patch(patch: dict) -> str | None:
    if not isinstance(patch, dict) or not patch:
        return "amend_rule needs a non-empty mechanics object"
    for path, val in patch.items():
        spec = MECHANIC_SPECS.get(path)
        if not spec:
            return f"unsupported constitutional mechanic {path}"
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
        if allowed is not None and val not in allowed:
            return f"unsupported value for {path}"
    return None


def render(law: dict) -> str:
    lines = ["# Constitution of the run", "", "## 100-series — immutable host physics", ""]
    lines.extend(f"{rid}. {text}" for rid, text in HARD_RULES.items())
    lines.extend(["", "## 200-series — executable interior law", ""])
    for rid, rule in sorted((law.get("rules") or {}).items()):
        lines.append(f"{rid}. {rule.get('text', '')}")
        for path, val in (rule.get("mechanics") or {}).items():
            lines.append(f"    - `{path}` = `{val}`")
    return "\n".join(lines) + "\n"

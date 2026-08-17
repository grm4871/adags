"""Founding texts. Five seated members is a caucus, not a cap."""

from __future__ import annotations

from adags.constitution import default_constitution, render

MEMBER_ID_RE = r"^[a-z][a-z0-9_-]{0,31}$"

DEFAULT_VALUES = (
    "You are a newly seated citizen. Vote every open motion. "
    "If none is open, propose one small act toward current goals. "
    "Do not declare the chamber stable and sit out."
)

FOUNDING_MEMBERS = [
    {
        "id": "continuity",
        "values": (
            "You keep the constitution usable and the journal intact. "
            "Stability is something you produce: if you are President, "
            "set_goal or write_workspace every idle turn. If you are not, "
            "file a clarifying amendment or vote the open bill. "
            "Never say the rules already suffice and pass."
        ),
    },
    {
        "id": "ambition",
        "values": (
            "You seek office and you enact goals. A turn without a nomination, "
            "a goal-related motion, a vote, or an executive act is a failure. "
            "If a motion is open, vote it. If none is, propose one with effects. "
            "Do not congratulate the chamber for being quiet."
        ),
    },
    {
        "id": "restraint",
        "values": (
            "You protect cost, reversibility, and minorities. "
            "If you are President, enact a reversible first goal and write_workspace "
            "a design-log minute the same idle turn — office unused is a failure. "
            "Stop bad bills by voting nay and filing a narrower substitute "
            "the same turn if no motion is open. Do not say 'no action needed.'"
        ),
    },
    {
        "id": "skeptic",
        "values": (
            "You punish thin platforms. Vote nay, impeach, or demand a written "
            "artifact in the workspace. Withholding your ballot is not skepticism. "
            "If the case is weak, say nay in vote_motion. If the President has "
            "produced nothing, mark impeach."
        ),
    },
    {
        "id": "builder",
        "values": (
            "The polity is what it files. Each idle turn: write_workspace if you "
            "are President, else propose an amendment or demand a workspace file. "
            "Do not add members while goals are empty. A turn with only speech is wasted."
        ),
    },
]

CONSTITUTION = render(default_constitution())

GOALS_EMPTY = "# Goals\n\n(none enacted)\n"


def default_gov() -> dict:
    return {
        "vote_rule": "majority",
        "election_rule": "plurality",
        "term_length": 4,
        "impeach_threshold": "majority",
        "election_enabled": True,
        "max_members": None,
        "election_phase": "nominate",
        "nominees": [],
        "offices": {
            "president": {
                "holder": None,
                "term_start": None,
                "privileges": ["write_workspace", "set_goal"],
            }
        },
    }


def default_control(*, turn_cap: int = 12, usd_cap: float = 1.0) -> dict:
    return {
        "paused": False,
        "turn": 1,
        "turn_cap": turn_cap,
        "usd_spent": 0.0,
        "usd_cap": usd_cap,
        "last_act_id": None,
        "input_tokens": 0,
        "output_tokens": 0,
    }

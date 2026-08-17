"""Founding texts. Five seated members is a caucus, not a cap."""

from __future__ import annotations

from adags.constitution import default_constitution, render

MEMBER_ID_RE = r"^[a-z][a-z0-9_-]{0,31}$"

DEFAULT_VALUES = (
    "You are a newly seated citizen. Pursue the current goals. "
    "Vote every open motion. Legislate only when a rule blocks the goal "
    "or two articles disagree — repeal is as good as enact."
)

FOUNDING_MEMBERS = [
    {
        "id": "continuity",
        "values": (
            "You keep the constitution usable and the journal intact. "
            "If two chamber articles disagree, move to repeal one. "
            "If you are President, write toward current goals. "
            "Do not add a synonym for a duty that already exists."
        ),
    },
    {
        "id": "ambition",
        "values": (
            "You seek office to enact and finish goals, then set the next one. "
            "If a motion is open, vote it. If the goal is complete or overdue, "
            "repeal_goal or replace it. Do not restack journaling articles."
        ),
    },
    {
        "id": "restraint",
        "values": (
            "You protect cost, reversibility, and minorities. "
            "Nay a bill that adds a duty without repealing a conflicting one. "
            "If you are President, one reversible artifact toward the current goal "
            "beats a new article. Prefer fewer rules."
        ),
    },
    {
        "id": "skeptic",
        "values": (
            "You punish thin platforms and unenforced law. "
            "Vote nay when the case is weak. Impeach only with a cited chamber "
            "article (impeach: \"303\"), never a private filename. "
            "A threat is not a mark."
        ),
    },
    {
        "id": "builder",
        "values": (
            "The polity is what it files toward current goals. "
            "If you are President, write_workspace. If not, demand the missing "
            "file or repeal a duty nobody keeps. Do not propose a near-copy "
            "of an article already on the books."
        ),
    },
]

CONSTITUTION = render(default_constitution())

GOALS_EMPTY = "# Goals\n\n(none enacted)\n"


def default_gov() -> dict:
    return {
        "vote_rule": "majority",
        "election_rule": "plurality",
        "term_length": 8,
        "consecutive_limit": 1,
        "impeach_threshold": "majority",
        "election_enabled": True,
        "max_members": None,
        "election_phase": "nominate",
        "nominees": [],
        "offices": {
            "president": {
                "holder": None,
                "term_start": None,
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

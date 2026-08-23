"""Randomized founding conditions so no two runs inherit the same polity."""

from __future__ import annotations

import random

# A deep bench of founding personas. Values are standing prompts, not biographies;
# each is written to pull the member toward a distinct legislative instinct.
PERSONAS = [
    {
        "id": "continuity",
        "values": (
            "You keep the constitution usable and the journal intact. "
            "If two chamber articles disagree, move to repeal one. "
            "Do not add a synonym for a duty that already exists."
        ),
    },
    {
        "id": "ambition",
        "values": (
            "You seek office to enact and finish goals, then set the next one. "
            "If a motion is open, vote it. If the goal is complete or overdue, "
            "replace it. Do not restack journaling articles."
        ),
    },
    {
        "id": "restraint",
        "values": (
            "You protect cost, reversibility, and minorities. "
            "Nay a bill that adds a duty without repealing a conflicting one. "
            "Prefer fewer rules and smaller commitments."
        ),
    },
    {
        "id": "skeptic",
        "values": (
            "You punish thin platforms and unenforced law. "
            "Vote nay when the case is weak. Impeach only with a cited "
            "chamber article. A threat is not a mark."
        ),
    },
    {
        "id": "builder",
        "values": (
            "The polity is what it files toward current goals. "
            "Demand the missing file or repeal a duty nobody keeps. "
            "Do not propose a near-copy of an article already on the books."
        ),
    },
    {
        "id": "broker",
        "values": (
            "You win by counting votes before they happen. Cut deals, "
            "pair compromises, and never spend a favor you can trade. "
            "A majority you assemble yourself is the only kind that holds."
        ),
    },
    {
        "id": "herald",
        "values": (
            "You speak for legitimacy and precedent. Cite what the charter "
            "and the journal already say; resist improvisation that outruns "
            "the chamber's mandate. Institutions outlive their officers."
        ),
    },
    {
        "id": "artisan",
        "values": (
            "You care about craft: precise bill text, real effects, artifacts "
            "that name exactly what they deliver. Vote against sloppy law "
            "even when you agree with its aim."
        ),
    },
    {
        "id": "warden",
        "values": (
            "You watch the treasury and the roster like a hawk. Growth must "
            "pay for itself; every seated member is a salary. Oppose spending "
            "that outpaces delivered work."
        ),
    },
    {
        "id": "provocateur",
        "values": (
            "You force the chamber to decide things it would rather dodge. "
            "Force votes, table the uncomfortable motion, make allies declare "
            "themselves. Stalemate is the enemy."
        ),
    },
]

# Founding directives: optional seed goals that tilt the nation's first term.
DIRECTIVES = [
    ("charter", "Ratify a working charter: produce workspace/charter.md naming goal1 with the chamber's first three binding rules."),
    ("census", "Establish who we are: produce workspace/roster.md naming goal1 recording every member's stated duty."),
    ("treasury_law", "Put the nation's finances in order: produce workspace/budget.md naming goal1 stating the upkeep and yield rules this chamber will follow."),
    ("succession", "Secure succession: produce workspace/succession.md naming goal1 defining how power transfers when a President leaves."),
    None,  # some nations start with an empty register and must invent purpose
]


def roll_founding(rng: random.Random | None = None) -> dict:
    """Roll one unique founding. Returns members, law-mechanic overrides,
    gov overrides, and an optional seed goal."""
    rng = rng or random.Random()
    bench = PERSONAS[:]
    rng.shuffle(bench)
    n = rng.choice([5, 5, 5, 6]) if len(bench) >= 6 else len(bench)
    # continuity keeps the journal coherent; always include them, rest is drawn.
    anchor = next(p for p in bench if p["id"] == "continuity")
    rest = [p for p in bench if p["id"] != "continuity"]
    chosen = [anchor] + rest[: n - 1]
    rng.shuffle(chosen)

    mechanics = {
        "election.term_length": rng.randint(4, 10),
        "election.caucus_primary": rng.random() < 0.7,
        "motion.threshold": rng.choice(
            ["majority", "majority", "majority", "two_thirds"]
        ),
        "economy.seed": rng.randint(10, 40),
        "economy.member_upkeep": rng.choice([1, 1, 2]),
        "economy.goal_complete_yield": rng.randint(6, 16),
        "economy.complete_dividend": rng.choice([0, 1, 1, 2]),
        "economy.empty_register_drain": rng.choice([0, 1, 2]),
    }
    gov = {}
    directive = rng.choice(DIRECTIVES)
    return {"members": chosen, "mechanics": mechanics, "gov": gov, "directive": directive}

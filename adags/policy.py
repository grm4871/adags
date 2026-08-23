"""Private nation policy: executive brief inherited across presidencies."""

from __future__ import annotations

from pathlib import Path

POLICY_FILE = "policy.md"
POLICY_CARD_LIMIT = 1200
CAMPAIGN_LIMIT = 400

DEFAULT_POLICY = """# Nation policy

Standing executive brief. Each President inherits this file and revises it.
It is not chamber law and not a workspace proof file. The floor does not see it.

## Direction
(none yet — first President: write the campaign you won on)

## Commitments
(none yet)

## Memory
Founded empty. Successors: keep what still binds; add what your campaign promised.
"""


def policy_path(root: Path) -> Path:
    return Path(root) / POLICY_FILE


def ensure_policy(root: Path) -> str:
    path = policy_path(root)
    if not path.exists():
        path.write_text(DEFAULT_POLICY, encoding="utf-8")
        return DEFAULT_POLICY
    return path.read_text(encoding="utf-8", errors="replace")


def load_policy(root: Path) -> str:
    return ensure_policy(root)


def save_policy(root: Path, body: str) -> str:
    """Write the policy and return the previous body."""
    path = policy_path(root)
    old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    path.write_text(body, encoding="utf-8")
    return old


def campaign_text(workspace: Path, member_id: str) -> str:
    path = Path(workspace) / "platforms" / f"{member_id}.md"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def policy_card(
    *,
    policy: str,
    campaign: str = "",
    due: bool = False,
    editor: str | None = None,
    edited_turn: int | None = None,
) -> str:
    """President-only card block. Empty string if there is nothing to show."""
    text = (policy or "").strip() or DEFAULT_POLICY.strip()
    if len(text) > POLICY_CARD_LIMIT:
        text = text[: POLICY_CARD_LIMIT] + "\n…"
    lines = [
        "Nation policy (private to this office; your successor inherits it):",
        text,
    ]
    if editor or edited_turn is not None:
        who = editor or "unknown"
        when = f" turn {edited_turn}" if edited_turn is not None else ""
        lines.append(f"Last edited by {who}{when}.")
    if campaign.strip():
        plat = campaign.strip()
        if len(plat) > CAMPAIGN_LIMIT:
            plat = plat[:CAMPAIGN_LIMIT] + "\n…"
        lines.append("Your campaign (fold this into Direction and Commitments; do not blank inherited sections you still agree with):")
        lines.append(plat)
    if due:
        lines.append(
            "HOST: you just took this office. executive edit_policy with the full revised "
            "document this term. Remember the campaign you won on. Reference this policy "
            "when you set_goal or write_workspace."
        )
    else:
        lines.append(
            "Reference this policy when you act. executive edit_policy when the campaign "
            "or the world requires a revision; send the full document, not a diff."
        )
    return "\n".join(lines)

"""
Membership tier logic for Nils Sjöberg.
Handles tier resolution, feature gating, and message limits.
"""

from datetime import datetime, timezone

FREE_DAILY_LIMIT = 5

PREMIUM_FEATURES = {
    "attachments",
    "workout_export",
    "structured_plans",
}


def get_user_tier(subscription: dict | None, is_admin: bool) -> str:
    """Resolve effective tier for a user."""
    if is_admin:
        return "premium"

    if not subscription:
        return "free"

    status = subscription.get("status", "")
    tier = subscription.get("tier", "free")

    # Active premium subscription
    if tier == "premium" and status == "active":
        return "premium"

    # Trialing: check if trial period is still valid
    if status == "trialing":
        trial_ends = subscription.get("trial_ends_at")
        if trial_ends:
            if isinstance(trial_ends, str):
                try:
                    trial_ends = datetime.fromisoformat(trial_ends.replace("Z", "+00:00"))
                except ValueError:
                    return "free"
            if datetime.now(timezone.utc) < trial_ends:
                return "premium"

    return "free"


def can_send_message(tier: str, daily_count: int) -> bool:
    """Check if user can send another message."""
    if tier == "premium":
        return True
    return daily_count < FREE_DAILY_LIMIT


def can_use_feature(tier: str, feature: str) -> bool:
    """Check if a feature is available for this tier."""
    if tier == "premium":
        return True
    return feature not in PREMIUM_FEATURES


def messages_remaining(tier: str, daily_count: int) -> int | None:
    """Return messages remaining today, or None if unlimited."""
    if tier == "premium":
        return None
    return max(0, FREE_DAILY_LIMIT - daily_count)


def trial_days_remaining(subscription: dict | None) -> int | None:
    """Return days remaining in trial, or None if not trialing."""
    if not subscription:
        return None
    if subscription.get("status") != "trialing":
        return None
    trial_ends = subscription.get("trial_ends_at")
    if not trial_ends:
        return None
    if isinstance(trial_ends, str):
        try:
            trial_ends = datetime.fromisoformat(trial_ends.replace("Z", "+00:00"))
        except ValueError:
            return None
    delta = trial_ends - datetime.now(timezone.utc)
    return max(0, delta.days)

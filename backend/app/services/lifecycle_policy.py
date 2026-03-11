"""Compute effective lifecycle policy for a user (tier override > system default)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import SystemSetting, User


async def get_effective_lifecycle(db: AsyncSession, user: User) -> dict:
    """Return the effective lifecycle policy for a user.

    Tier overrides take precedence over system defaults.
    Returns dict with idle_shutdown_days, idle_destroy_days, account_inactive_days.
    A value of 0 means exempt/disabled for that policy.
    """
    result = await db.execute(
        select(SystemSetting).where(
            SystemSetting.key.in_([
                "idle_shutdown_days", "idle_destroy_days", "account_inactive_days",
            ])
        )
    )
    defaults = {s.key: int(s.value or "0") for s in result.scalars().all()}

    shutdown = defaults.get("idle_shutdown_days", 14)
    destroy = defaults.get("idle_destroy_days", 30)
    account = defaults.get("account_inactive_days", 0)

    # Tier overrides (if set, they replace system defaults)
    if user.tier:
        if user.tier.idle_shutdown_days is not None:
            shutdown = user.tier.idle_shutdown_days
        if user.tier.idle_destroy_days is not None:
            destroy = user.tier.idle_destroy_days
        if user.tier.account_inactive_days is not None:
            account = user.tier.account_inactive_days

    return {
        "idle_shutdown_days": shutdown,
        "idle_destroy_days": destroy,
        "account_inactive_days": account,
    }

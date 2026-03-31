"""In-memory setup state to avoid per-request DB checks.

The flag is populated on startup and flipped when /api/setup/init completes.
"""

import logging

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

_initialized: bool | None = None


def is_initialized() -> bool:
    """Return True if the app has been initialized (at least one admin exists).

    Returns True by default if the state has not been checked yet (safe
    fallback so existing deployments are not blocked).
    """
    if _initialized is None:
        return True
    return _initialized


def mark_initialized() -> None:
    """Mark the app as initialized (called after setup completes)."""
    global _initialized
    _initialized = True


async def check_initialized() -> None:
    """Query the DB once to set the in-memory flag. Called during startup."""
    global _initialized
    try:
        from app.core.database import async_session
        from app.models.models import User, UserRole

        async with async_session() as db:
            result = await db.execute(select(func.count()).select_from(User).where(User.role == UserRole.ADMIN))
            count = result.scalar() or 0
            _initialized = count > 0
            logger.info(
                "Setup state: %s",
                "initialized" if _initialized else "awaiting setup",
            )
    except Exception:
        # DB might not be ready (no migrations yet) - allow through
        _initialized = None
        logger.warning("Could not check setup state - defaulting to pass-through")

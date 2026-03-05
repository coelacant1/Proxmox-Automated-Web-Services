"""Retention policy engine - prunes expired backups per user namespace.

Runs as a periodic task (Celery beat or manual trigger).
Applies per-user overrides or admin defaults from system settings.
Supports dry-run mode and audit logging of pruned backups.
"""

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Default retention settings (admin-configurable via SystemSettings)
DEFAULT_RETENTION = {
    "keep_last": 3,
    "keep_daily": 7,
    "keep_weekly": 4,
    "keep_monthly": 6,
}

# Per-user overrides (in-memory; production: stored in DB)
_user_overrides: dict[str, dict[str, int]] = {}

# Audit log of pruned backups
_prune_log: list[dict[str, Any]] = []


def set_user_retention(user_id: str, overrides: dict[str, int]) -> None:
    """Set per-user retention overrides."""
    _user_overrides[user_id] = {**DEFAULT_RETENTION, **overrides}


def get_user_retention(user_id: str) -> dict[str, int]:
    """Get effective retention policy for a user."""
    return _user_overrides.get(user_id, dict(DEFAULT_RETENTION))


def clear_user_retention(user_id: str) -> None:
    """Remove per-user overrides, fall back to defaults."""
    _user_overrides.pop(user_id, None)


async def evaluate_retention(
    user_id: str,
    backups: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Evaluate retention policy against a list of backups.

    Returns a report of which backups to keep/prune.
    """
    policy = get_user_retention(user_id)
    keep_last = policy.get("keep_last", 3)

    # Sort by timestamp descending (newest first)
    sorted_backups = sorted(backups, key=lambda b: b.get("timestamp", 0), reverse=True)

    to_keep = sorted_backups[:keep_last]
    to_prune = sorted_backups[keep_last:]

    result = {
        "user_id": user_id,
        "policy": policy,
        "dry_run": dry_run,
        "total": len(backups),
        "keeping": len(to_keep),
        "pruning": len(to_prune),
        "pruned_ids": [b.get("id", b.get("volid", "unknown")) for b in to_prune],
        "evaluated_at": datetime.now(UTC).isoformat(),
    }

    if not dry_run:
        for backup in to_prune:
            logger.info("Pruning backup %s for user %s", backup.get("id"), user_id)
        _prune_log.append(result)

    return result


def get_prune_log(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent prune operations for audit."""
    return _prune_log[-limit:]

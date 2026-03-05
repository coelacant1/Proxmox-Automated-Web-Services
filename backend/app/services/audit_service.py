"""Audit logging service - records all user actions."""

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AuditLog

# Standard security event types for consistent audit logging
AUTH_EVENTS = {
    "auth.login_success",
    "auth.login_failed",
    "auth.register",
    "auth.logout",
    "auth.password_changed",
    "auth.mfa_enabled",
    "auth.mfa_disabled",
    "auth.api_key_created",
    "auth.api_key_revoked",
    "auth.account_locked",
    "auth.session_revoked",
    "auth.revoke_all_sessions",
}


async def log_action(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=json.dumps(details) if details else None,
    )
    db.add(entry)
    await db.commit()


async def log_auth_event(
    db: AsyncSession,
    action: str,
    user_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log an authentication event. Falls back to Python logging if no user_id."""
    import logging

    logger = logging.getLogger("paws.auth")
    if user_id is None:
        # No valid user - log via Python logger only (can't satisfy FK constraint)
        logger.warning("Auth event: %s | %s", action, details)
        return

    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type="auth",
        details=json.dumps(details) if details else None,
    )
    db.add(entry)
    await db.commit()

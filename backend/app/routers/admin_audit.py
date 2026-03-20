"""Admin audit log viewing endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.core.pagination import PaginatedParams, PaginatedResponse
from app.models.models import AuditLog, User
from app.schemas.schemas import AuditLogRead

router = APIRouter(prefix="/api/admin/audit-logs", tags=["admin"])


@router.get("/", response_model=PaginatedResponse[AuditLogRead])
async def list_audit_logs(
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    params: PaginatedParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List audit logs with optional filters."""
    base = select(AuditLog)
    if user_id:
        base = base.where(AuditLog.user_id == uuid.UUID(user_id))
    if action:
        base = base.where(AuditLog.action == action)
    if resource_type:
        base = base.where(AuditLog.resource_type == resource_type)

    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0

    query = base.order_by(AuditLog.created_at.desc()).offset(params.offset).limit(params.per_page)
    result = await db.execute(query)
    return PaginatedResponse.create(list(result.scalars().all()), total, params)


@router.get("/security-dashboard")
async def security_dashboard(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Admin security dashboard - failed logins, locked accounts, MFA adoption."""
    now = datetime.now(UTC)
    last_hour = now - timedelta(hours=1)
    last_24h = now - timedelta(hours=24)

    # Failed logins in the last hour
    failed_1h = await db.execute(
        select(func.count()).where(
            AuditLog.action.in_(["auth.login_failed", "user.login_failed"]),
            AuditLog.created_at >= last_hour,
        )
    )

    # Failed logins in the last 24 hours
    failed_24h = await db.execute(
        select(func.count()).where(
            AuditLog.action.in_(["auth.login_failed", "user.login_failed"]),
            AuditLog.created_at >= last_24h,
        )
    )

    # Currently locked accounts
    locked_accounts = await db.execute(
        select(func.count()).where(User.locked_until.isnot(None), User.locked_until > now)
    )

    # Recent security events (last 10)
    recent_security = await db.execute(
        select(AuditLog)
        .where(AuditLog.action.like("auth.%"))
        .order_by(AuditLog.created_at.desc())
        .limit(10)
    )

    return {
        "failed_logins_1h": failed_1h.scalar() or 0,
        "failed_logins_24h": failed_24h.scalar() or 0,
        "locked_accounts": locked_accounts.scalar() or 0,
        "recent_security_events": [
            {
                "action": log.action,
                "user_id": str(log.user_id) if log.user_id else None,
                "details": log.details,
                "timestamp": log.created_at.isoformat() if log.created_at else None,
            }
            for log in recent_security.scalars().all()
        ],
    }

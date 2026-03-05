"""Usage tracking and dashboard data endpoints."""

import json

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import AuditLog, QuotaRequest, Resource, User, UserQuota

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def user_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Unified dashboard data for the current user."""
    # Resource counts by type
    result = await db.execute(
        select(Resource.resource_type, func.count(Resource.id))
        .where(Resource.owner_id == user.id, Resource.status != "destroyed")
        .group_by(Resource.resource_type)
    )
    counts = {row[0]: row[1] for row in result.all()}

    # Quota
    q_result = await db.execute(select(UserQuota).where(UserQuota.user_id == user.id))
    quota = q_result.scalar_one_or_none()

    # Recent activity
    activity_result = await db.execute(
        select(AuditLog).where(AuditLog.user_id == user.id).order_by(desc(AuditLog.created_at)).limit(10)
    )
    recent_activity = [
        {
            "action": log.action,
            "resource_type": log.resource_type,
            "details": json.loads(log.details) if log.details else None,
            "created_at": str(log.created_at),
        }
        for log in activity_result.scalars().all()
    ]

    # Resource status breakdown
    status_result = await db.execute(
        select(Resource.status, func.count(Resource.id))
        .where(Resource.owner_id == user.id, Resource.status != "destroyed")
        .group_by(Resource.status)
    )
    status_counts = {row[0]: row[1] for row in status_result.all()}

    return {
        "resources": {
            "vms": counts.get("vm", 0),
            "containers": counts.get("lxc", 0),
            "networks": counts.get("network", 0),
            "storage_buckets": counts.get("storage", 0),
        },
        "quota": {
            "max_vms": quota.max_vms if quota else 5,
            "max_containers": quota.max_containers if quota else 10,
            "max_vcpus": quota.max_vcpus if quota else 16,
            "max_ram_mb": quota.max_ram_mb if quota else 32768,
            "max_disk_gb": quota.max_disk_gb if quota else 500,
        },
        "status_breakdown": status_counts,
        "recent_activity": recent_activity,
    }


@router.get("/admin/overview")
async def admin_overview(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Admin-level platform overview."""
    user_count = await db.execute(select(func.count(User.id)))
    active_users = await db.execute(select(func.count(User.id)).where(User.is_active.is_(True)))
    total_resources = await db.execute(
        select(Resource.resource_type, func.count(Resource.id))
        .where(Resource.status != "destroyed")
        .group_by(Resource.resource_type)
    )
    resource_counts = {row[0]: row[1] for row in total_resources.all()}

    active_resources = await db.execute(
        select(func.count(Resource.id)).where(Resource.status.in_(["running", "provisioning", "stopped"]))
    )

    pending_qr = await db.execute(
        select(func.count(QuotaRequest.id)).where(QuotaRequest.status == "pending")
    )

    recent_users = await db.execute(select(User).order_by(desc(User.created_at)).limit(5))

    return {
        "total_users": user_count.scalar() or 0,
        "active_users": active_users.scalar() or 0,
        "total_resources": resource_counts,
        "active_resources": active_resources.scalar() or 0,
        "pending_quota_requests": pending_qr.scalar() or 0,
        "recent_users": [
            {"username": u.username, "email": u.email, "created_at": str(u.created_at)}
            for u in recent_users.scalars().all()
        ],
    }


@router.get("/usage")
async def usage_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Resource usage summary for the current user."""
    # Get all active resources with specs
    result = await db.execute(select(Resource).where(Resource.owner_id == user.id, Resource.status != "destroyed"))
    resources = result.scalars().all()

    total_vcpus = 0
    total_ram_mb = 0
    total_disk_gb = 0
    for r in resources:
        if r.specs:
            specs = json.loads(r.specs)
            total_vcpus += specs.get("cores", 0)
            total_ram_mb += specs.get("memory_mb", 0)
            total_disk_gb += specs.get("disk_gb", 0)

    return {
        "total_vcpus_allocated": total_vcpus,
        "total_ram_mb_allocated": total_ram_mb,
        "total_disk_gb_allocated": total_disk_gb,
        "resource_count": len(resources),
    }

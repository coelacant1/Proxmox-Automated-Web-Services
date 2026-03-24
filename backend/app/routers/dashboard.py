"""Usage tracking and dashboard data endpoints."""

import json
import time
from datetime import UTC

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import (
    VPC,
    Alarm,
    AuditLog,
    Backup,
    DNSRecord,
    QuotaRequest,
    Resource,
    SecurityGroup,
    ServiceEndpoint,
    SSHKeyPair,
    StorageBucket,
    User,
    UserQuota,
    Volume,
)

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

    # Compute actual vCPU / RAM / Disk usage from active resources
    active_resources = await db.execute(
        select(Resource).where(
            Resource.owner_id == user.id,
            Resource.status.in_(["running", "stopped", "provisioning", "paused", "suspended"]),
        )
    )
    total_vcpus = 0
    total_ram_mb = 0
    total_disk_gb = 0
    for r in active_resources.scalars().all():
        if r.specs:
            specs = json.loads(r.specs)
            total_vcpus += specs.get("cores", 0)
            total_ram_mb += specs.get("memory_mb", 0)
            total_disk_gb += specs.get("disk_gb", 0)

    # VPC (network) count
    vpc_result = await db.execute(select(func.count(VPC.id)).where(VPC.owner_id == user.id))
    vpc_count = vpc_result.scalar() or 0

    # Snapshot count
    snapshot_count = 0
    try:
        snap_result = await db.execute(
            select(func.count(Backup.id)).where(
                Backup.owner_id == user.id,
                Backup.backup_type == "snapshot",
            )
        )
        snapshot_count = snap_result.scalar() or 0
    except Exception:
        pass

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

    # S3 storage size and bucket count
    storage_size_result = await db.execute(
        select(func.coalesce(func.sum(StorageBucket.size_bytes), 0)).where(StorageBucket.owner_id == user.id)
    )
    storage_size_bytes = storage_size_result.scalar() or 0
    bucket_count_result = await db.execute(
        select(func.count(StorageBucket.id)).where(StorageBucket.owner_id == user.id)
    )
    bucket_count = bucket_count_result.scalar() or 0

    return {
        "resources": {
            "vms": counts.get("vm", 0),
            "containers": counts.get("lxc", 0),
            "networks": vpc_count,
            "storage_buckets": bucket_count,
            "storage_size_gb": round(storage_size_bytes / 1_073_741_824, 3),
            "vcpus_used": total_vcpus,
            "ram_mb_used": total_ram_mb,
            "disk_gb_used": total_disk_gb,
            "snapshots": snapshot_count,
        },
        "quota": {
            "max_vms": quota.max_vms if quota else 5,
            "max_containers": quota.max_containers if quota else 10,
            "max_vcpus": quota.max_vcpus if quota else 16,
            "max_ram_mb": quota.max_ram_mb if quota else 32768,
            "max_disk_gb": quota.max_disk_gb if quota else 500,
            "max_snapshots": quota.max_snapshots if quota else 10,
            "max_backups": quota.max_backups if quota else 20,
            "max_backup_size_gb": quota.max_backup_size_gb if quota else 100,
            "max_networks": quota.max_networks if quota else 3,
            "max_subnets_per_network": quota.max_subnets_per_network if quota else 5,
            "max_elastic_ips": quota.max_elastic_ips if quota else 5,
            "max_buckets": quota.max_buckets if quota else 5,
            "max_storage_gb": quota.max_storage_gb if quota else 50,
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

    pending_qr = await db.execute(select(func.count(QuotaRequest.id)).where(QuotaRequest.status == "pending"))

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


# ---- Admin Analytics Endpoints ----


@router.get("/admin/analytics")
async def admin_analytics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Real-time analytics: active users, request counts over time, login history."""
    from datetime import datetime

    from app.services.rate_limiter import get_redis

    now = time.time()
    current_hour = int(now // 3600) * 3600

    # -- Active users (seen in last 15 minutes) --
    active_users_raw: list = []
    try:
        r = await get_redis()
        cutoff = now - 900  # 15 minutes
        active_ids = await r.zrangebyscore("analytics:active_users", cutoff, "+inf", withscores=True)
        if active_ids:
            user_ids = [uid for uid, _ in active_ids]
            result = await db.execute(
                select(User.id, User.username, User.email, User.role).where(User.id.in_(user_ids))
            )
            user_map = {str(u.id): {"username": u.username, "email": u.email, "role": u.role} for u in result.all()}
            for uid, score in active_ids:
                info = user_map.get(uid, {"username": "unknown", "email": "", "role": ""})
                active_users_raw.append(
                    {
                        **info,
                        "last_seen": datetime.fromtimestamp(score, tz=UTC).isoformat(),
                    }
                )
    except Exception:
        pass

    # -- Request counts per hour (last 24 hours) --
    request_history: list = []
    try:
        r = await get_redis()
        pipe = r.pipeline()
        for i in range(24):
            bucket = current_hour - (i * 3600)
            pipe.get(f"analytics:requests:{bucket}")
        results = await pipe.execute()
        for i, count in enumerate(results):
            bucket = current_hour - (i * 3600)
            request_history.append(
                {
                    "time": datetime.fromtimestamp(bucket, tz=UTC).isoformat(),
                    "requests": int(count) if count else 0,
                }
            )
        request_history.reverse()
    except Exception:
        pass

    # -- Top endpoints this hour --
    top_endpoints: list = []
    try:
        r = await get_redis()
        ep_data = await r.hgetall(f"analytics:endpoints:{current_hour}")
        if ep_data:
            sorted_eps = sorted(ep_data.items(), key=lambda x: int(x[1]), reverse=True)[:15]
            top_endpoints = [{"endpoint": k, "count": int(v)} for k, v in sorted_eps]
    except Exception:
        pass

    # -- Login history (from audit logs, last 7 days) --
    from datetime import timedelta

    seven_days_ago = datetime.now(tz=UTC) - timedelta(days=7)

    # Logins per day
    login_result = await db.execute(
        select(
            cast(AuditLog.created_at, Date).label("day"),
            func.count(AuditLog.id),
        )
        .where(
            AuditLog.action.in_(["login", "login_success", "oauth_login"]),
            AuditLog.created_at >= seven_days_ago,
        )
        .group_by("day")
        .order_by("day")
    )
    logins_by_day = [{"date": str(row[0]), "logins": row[1]} for row in login_result.all()]

    # Recent logins
    recent_logins_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.action.in_(["login", "login_success", "oauth_login"]))
        .order_by(desc(AuditLog.created_at))
        .limit(20)
    )
    recent_logins_raw = recent_logins_result.scalars().all()
    # Resolve usernames
    login_user_ids = list({entry.user_id for entry in recent_logins_raw})
    user_result = (
        await db.execute(select(User.id, User.username, User.email).where(User.id.in_(login_user_ids)))
        if login_user_ids
        else None
    )
    login_user_map = (
        {str(u.id): {"username": u.username, "email": u.email} for u in user_result.all()} if user_result else {}
    )

    recent_logins = [
        {
            "username": login_user_map.get(str(entry.user_id), {}).get("username", "unknown"),
            "email": login_user_map.get(str(entry.user_id), {}).get("email", ""),
            "action": entry.action,
            "details": json.loads(entry.details) if entry.details else None,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
        for entry in recent_logins_raw
    ]

    # -- Total requests today --
    total_today = 0
    try:
        r = await get_redis()
        pipe = r.pipeline()
        day_start = int(now // 86400) * 86400
        for h in range(24):
            bucket = day_start + (h * 3600)
            pipe.get(f"analytics:requests:{bucket}")
        results = await pipe.execute()
        total_today = sum(int(c) for c in results if c)
    except Exception:
        pass

    return {
        "active_users": active_users_raw,
        "active_user_count": len(active_users_raw),
        "request_history": request_history,
        "total_requests_today": total_today,
        "top_endpoints": top_endpoints,
        "logins_by_day": logins_by_day,
        "recent_logins": recent_logins,
    }


# ---- Admin All-Resources Endpoint ----

RESOURCE_CATEGORIES = {
    "instances": {"model": Resource, "filter": lambda q: q.where(Resource.status != "destroyed")},
    "volumes": {"model": Volume},
    "vpcs": {"model": VPC},
    "security_groups": {"model": SecurityGroup},
    "storage_buckets": {"model": StorageBucket},
    "backups": {"model": Backup},
    "dns_records": {"model": DNSRecord},
    "alarms": {"model": Alarm},
    "ssh_keys": {"model": SSHKeyPair},
    "endpoints": {"model": ServiceEndpoint},
}


def _serialize_row(row, model_name: str, user_map: dict) -> dict:
    """Generic serializer for admin resource listing rows."""
    d: dict = {"id": str(row.id), "owner_id": str(row.owner_id)}
    d["owner_username"] = user_map.get(str(row.owner_id), "unknown")

    if model_name == "instances":
        d.update(
            {
                "display_name": row.display_name,
                "resource_type": row.resource_type,
                "status": row.status,
                "proxmox_vmid": row.proxmox_vmid,
                "proxmox_node": row.proxmox_node,
                "specs": json.loads(row.specs) if row.specs else {},
                "created_at": str(row.created_at),
                "last_accessed_at": row.last_accessed_at.isoformat() if row.last_accessed_at else None,
            }
        )
    elif model_name == "volumes":
        d.update(
            {
                "name": row.name,
                "size_gib": row.size_gib,
                "storage_pool": getattr(row, "storage_pool", None),
                "status": getattr(row, "status", None),
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )
    elif model_name == "vpcs":
        d.update(
            {
                "name": row.name,
                "cidr": row.cidr,
                "vxlan_tag": getattr(row, "vxlan_tag", None),
                "is_default": getattr(row, "is_default", False),
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )
    elif model_name == "security_groups":
        d.update(
            {
                "name": row.name,
                "description": row.description,
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )
    elif model_name == "storage_buckets":
        d.update(
            {
                "name": row.name,
                "region": getattr(row, "region", None),
                "versioning_enabled": getattr(row, "versioning_enabled", False),
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )
    elif model_name == "backups":
        d.update(
            {
                "backup_type": row.backup_type,
                "status": getattr(row, "status", None),
                "resource_id": str(row.resource_id) if row.resource_id else None,
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )
    elif model_name == "dns_records":
        d.update(
            {
                "name": row.name,
                "record_type": row.record_type,
                "value": getattr(row, "value", None),
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )
    elif model_name == "alarms":
        d.update(
            {
                "name": row.name,
                "metric": getattr(row, "metric", None),
                "state": getattr(row, "state", None),
                "resource_id": str(row.resource_id) if row.resource_id else None,
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )
    elif model_name == "ssh_keys":
        d.update(
            {
                "name": row.name,
                "fingerprint": getattr(row, "fingerprint", None),
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )
    elif model_name == "endpoints":
        d.update(
            {
                "name": row.name,
                "protocol": getattr(row, "protocol", None),
                "subdomain": getattr(row, "subdomain", None),
                "fqdn": getattr(row, "fqdn", None),
                "is_active": getattr(row, "is_active", True),
                "resource_id": str(row.resource_id) if row.resource_id else None,
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )

    return d


@router.get("/admin/resources")
async def admin_all_resources(
    category: str = Query("instances", description="Resource category to list"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query("", description="Search filter"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all resources of a given category across all users."""
    if category not in RESOURCE_CATEGORIES:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"Unknown category: {category}. Valid: {list(RESOURCE_CATEGORIES.keys())}",
        )

    cat = RESOURCE_CATEGORIES[category]
    model = cat["model"]
    query = select(model)

    # Apply category-specific filters
    if "filter" in cat:
        query = cat["filter"](query)

    # Apply search filter
    if search:
        if hasattr(model, "display_name"):
            query = query.where(model.display_name.ilike(f"%{search}%"))
        elif hasattr(model, "name"):
            query = query.where(model.name.ilike(f"%{search}%"))

    # Count
    from sqlalchemy import func as sqfunc

    count_q = select(sqfunc.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Order and paginate
    if hasattr(model, "created_at"):
        query = query.order_by(desc(model.created_at))
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    rows = list(result.scalars().all())

    # Resolve owner usernames
    owner_ids = list({str(r.owner_id) for r in rows if r.owner_id})
    user_map: dict = {}
    if owner_ids:
        user_result = await db.execute(select(User.id, User.username).where(User.id.in_(owner_ids)))
        user_map = {str(u.id): u.username for u in user_result.all()}

    items = [_serialize_row(r, category, user_map) for r in rows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "categories": list(RESOURCE_CATEGORIES.keys()),
    }

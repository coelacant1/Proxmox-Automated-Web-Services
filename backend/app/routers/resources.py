"""User-facing resource endpoints with tenant isolation."""

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.core.pagination import PaginatedParams, PaginatedResponse
from app.models.models import ProjectMember, Resource, User, UserQuota
from app.schemas.schemas import QuotaRead, UsageResponse
from app.services.proxmox_client import proxmox_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resources", tags=["resources"])


@router.get("/")
async def list_my_resources(
    resource_type: str | None = None,
    project_id: uuid.UUID | None = Query(None, description="Filter by project"),
    params: PaginatedParams = Depends(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List resources owned by the current user with live status from Proxmox."""
    if project_id:
        member_q = select(ProjectMember.project_id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
        member_result = await db.execute(member_q)
        if not member_result.scalar_one_or_none() and user.role != "admin":
            base = select(Resource).where(Resource.id == None)  # noqa: E711 - empty result
        else:
            base = select(Resource).where(Resource.project_id == project_id)
    else:
        base = select(Resource).where(
            Resource.owner_id == user.id,
            Resource.status.notin_(["destroyed", "error", "creating"]),
        )

    if resource_type:
        base = base.where(Resource.resource_type == resource_type)

    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0

    query = base.offset(params.offset).limit(params.per_page).order_by(Resource.created_at.desc())
    result = await db.execute(query)
    resources = list(result.scalars().all())

    # Build VMID -> live info lookup from cluster resources (single API call)
    cluster_lookup: dict[int, dict] = {}
    try:
        for cr in proxmox_client.get_cluster_resources("vm"):
            vmid = cr.get("vmid")
            if vmid is not None:
                cluster_lookup[vmid] = cr
    except Exception:
        pass

    items = []
    for r in resources:
        item = {
            "id": str(r.id),
            "display_name": r.display_name,
            "resource_type": r.resource_type,
            "status": r.status,
            "proxmox_node": r.proxmox_node,
            "created_at": str(r.created_at),
        }

        # Enrich VMs/LXCs with live status from cluster lookup
        if r.resource_type in ("vm", "lxc") and r.proxmox_vmid:
            live = cluster_lookup.get(r.proxmox_vmid)
            if live:
                item["status"] = live.get("status", r.status)
                current_node = live.get("node")
                if current_node:
                    item["proxmox_node"] = current_node
                    # Update DB if node has changed (migration)
                    if current_node != r.proxmox_node:
                        r.proxmox_node = current_node

        items.append(item)

    # Commit any node updates from migrations
    try:
        await db.commit()
    except Exception:
        await db.rollback()

    return PaginatedResponse.create(items, total, params)


@router.get("/quota", response_model=QuotaRead)
async def get_my_quota(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get the current user's resource quotas."""
    result = await db.execute(select(UserQuota).where(UserQuota.user_id == user.id))
    quota = result.scalar_one_or_none()
    if quota is None:
        # Return defaults if no quota row exists
        return QuotaRead(
            max_vms=5, max_containers=10, max_vcpus=16, max_ram_mb=32768, max_disk_gb=500, max_snapshots=10
        )
    return quota


@router.get("/usage", response_model=UsageResponse)
async def get_my_usage(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get the current user's resource usage counts."""
    result = await db.execute(
        select(Resource.resource_type, func.count(Resource.id))
        .where(Resource.owner_id == user.id)
        .where(Resource.status != "destroyed")
        .group_by(Resource.resource_type)
    )
    usage = {row[0]: row[1] for row in result.all()}
    return UsageResponse(
        vms=usage.get("vm", 0),
        containers=usage.get("lxc", 0),
        networks=usage.get("network", 0),
        storage_buckets=usage.get("storage", 0),
    )

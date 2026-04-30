"""User-facing resource endpoints with tenant isolation."""

import logging
import re as _re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.core.pagination import PaginatedParams, PaginatedResponse
from app.models.models import ProjectMember, Resource, User, UserQuota
from app.schemas.schemas import QuotaRead, UsageResponse
from app.services.group_access import check_group_access
from app.services.proxmox_cache import get_cluster_resources as cached_cluster_resources
from app.services.proxmox_client import get_pve

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resources", tags=["resources"])


async def _get_accessible_resource(
    db: AsyncSession,
    user: User,
    resource_id: uuid.UUID,
    min_perm: str = "read",
) -> Resource:
    """Fetch a resource with ownership, admin, or group-access check."""
    result = await db.execute(select(Resource).where(Resource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    # Owner or global admin always allowed
    if resource.owner_id == user.id or user.role == "admin":
        return resource
    # Check group-level access
    if await check_group_access(db, user.id, "resource", resource_id, min_perm):
        return resource
    raise HTTPException(status_code=403, detail="Access denied")


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

    # Build VMID -> live info lookup from cluster resources (single API call per cluster, cached)
    cluster_lookup: dict[int, dict] = {}
    cluster_ids = {r.cluster_id for r in resources if hasattr(r, "cluster_id")}
    for cid in cluster_ids or {None}:
        for cr in await cached_cluster_resources(cid, "vm"):
            vmid = cr.get("vmid")
            if vmid is not None:
                cluster_lookup[vmid] = cr

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


# --- Resource Notes ---

_PAWS_ID_RE = _re.compile(r"^PAWS-ID:([0-9a-f-]{36})", _re.MULTILINE)


def parse_paws_id(description: str) -> str | None:
    """Extract the PAWS resource UUID from a Proxmox description field.

    Returns None if no PAWS-ID line is present.
    """
    if not description:
        return None
    m = _PAWS_ID_RE.search(description)
    return m.group(1) if m else None


def _build_paws_description(resource: Resource, owner: User | None, user_notes: str) -> str:
    """Build Proxmox description with PAWS metadata header + user notes."""
    username = owner.username if owner else "Unknown"
    email = (owner.email or "N/A") if owner else "N/A"
    owner_id = owner.id if owner else resource.owner_id
    lines = [
        f"PAWS-ID:{resource.id}",
        "",
        "PAWS Managed Resource",
        "",
        f"Owner: {username} ({email})",
        "",
        f"User ID: {owner_id}",
        "",
        f"Resource ID: {resource.id}",
        "",
        f"Name: {resource.display_name}",
        "",
        f"Created: {resource.created_at or 'N/A'}",
        "",
        "---",
        "",
        "This instance is managed by PAWS. Do not modify tags or description manually.",
    ]
    if user_notes and user_notes.strip():
        lines.extend(["", "---", "", "User Notes:", "", user_notes.strip()])
    return "\n".join(lines)


class ResourceNotesBody(BaseModel):
    notes: str


@router.get("/{resource_id}/notes")
async def get_resource_notes(
    resource_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get markdown notes for a resource."""
    resource = await _get_accessible_resource(db, user, resource_id, min_perm="read")
    return {"notes": resource.notes or ""}


@router.put("/{resource_id}/notes")
async def update_resource_notes(
    resource_id: uuid.UUID,
    body: ResourceNotesBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Update markdown notes for a resource. For VMs/LXCs, also syncs to Proxmox description."""
    resource = await _get_accessible_resource(db, user, resource_id, min_perm="operate")

    resource.notes = body.notes
    await db.commit()

    # Sync to Proxmox description: rebuild PAWS metadata + append user notes
    if resource.resource_type in ("vm", "lxc") and resource.proxmox_vmid and resource.proxmox_node:
        try:
            owner_result = await db.execute(select(User).where(User.id == resource.owner_id))
            owner = owner_result.scalar_one_or_none()
            description = _build_paws_description(resource, owner, body.notes)
            get_pve(resource.cluster_id).set_vm_description(resource.proxmox_node, resource.proxmox_vmid, description)
        except Exception:
            pass  # best-effort sync

    return {"notes": resource.notes or ""}

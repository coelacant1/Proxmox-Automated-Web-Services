"""User-facing resource endpoints with tenant isolation."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.core.pagination import PaginatedParams, PaginatedResponse
from app.models.models import ProjectMember, Resource, User, UserQuota
from app.schemas.schemas import QuotaRead, ResourceRead, UsageResponse

router = APIRouter(prefix="/api/resources", tags=["resources"])


@router.get("/", response_model=PaginatedResponse[ResourceRead])
async def list_my_resources(
    resource_type: str | None = None,
    project_id: uuid.UUID | None = Query(None, description="Filter by project"),
    params: PaginatedParams = Depends(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List resources owned by the current user, optionally filtered by project."""
    if project_id:
        # Show resources in a project the user has access to
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
        base = select(Resource).where(Resource.owner_id == user.id, Resource.status.notin_(["destroyed", "error", "creating"]))

    if resource_type:
        base = base.where(Resource.resource_type == resource_type)

    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0

    query = base.offset(params.offset).limit(params.per_page).order_by(Resource.created_at.desc())
    result = await db.execute(query)
    return PaginatedResponse.create(list(result.scalars().all()), total, params)


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

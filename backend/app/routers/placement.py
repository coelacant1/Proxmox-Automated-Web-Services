"""Placement groups API - manage anti-affinity and affinity rules for VM placement."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import Resource, User

router = APIRouter(prefix="/api/placement", tags=["placement"])

# Store placement groups in memory until model is added (lightweight)
# In production, this would be a proper model
_placement_groups: dict[str, dict] = {}


class PlacementGroupCreate(BaseModel):
    name: str
    strategy: str = "spread"  # spread (anti-affinity), cluster (affinity)


class PlacementGroupMember(BaseModel):
    resource_id: str


@router.get("/groups")
async def list_placement_groups(
    user: User = Depends(get_current_active_user),
):
    """List all placement groups for the user."""
    user_groups = [
        {**g, "id": gid}
        for gid, g in _placement_groups.items()
        if g["owner_id"] == str(user.id)
    ]
    return user_groups


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_placement_group(
    body: PlacementGroupCreate,
    user: User = Depends(get_current_active_user),
):
    """Create a placement group."""
    if body.strategy not in ("spread", "cluster"):
        raise HTTPException(status_code=400, detail="Strategy must be 'spread' or 'cluster'")

    gid = str(uuid.uuid4())
    _placement_groups[gid] = {
        "name": body.name,
        "strategy": body.strategy,
        "owner_id": str(user.id),
        "members": [],
    }
    return {"id": gid, **_placement_groups[gid]}


@router.post("/groups/{group_id}/members")
async def add_member(
    group_id: str,
    body: PlacementGroupMember,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Add a resource to a placement group."""
    group = _placement_groups.get(group_id)
    if not group or group["owner_id"] != str(user.id):
        raise HTTPException(status_code=404, detail="Placement group not found")

    # Verify resource ownership
    result = await db.execute(
        select(Resource).where(Resource.id == uuid.UUID(body.resource_id), Resource.owner_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Resource not found")

    if body.resource_id not in group["members"]:
        group["members"].append(body.resource_id)

    return {"status": "added", "group_id": group_id, "member_count": len(group["members"])}


@router.delete("/groups/{group_id}/members/{resource_id}")
async def remove_member(
    group_id: str,
    resource_id: str,
    user: User = Depends(get_current_active_user),
):
    """Remove a resource from a placement group."""
    group = _placement_groups.get(group_id)
    if not group or group["owner_id"] != str(user.id):
        raise HTTPException(status_code=404, detail="Placement group not found")

    if resource_id in group["members"]:
        group["members"].remove(resource_id)

    return {"status": "removed"}


@router.delete("/groups/{group_id}")
async def delete_placement_group(
    group_id: str,
    user: User = Depends(get_current_active_user),
):
    """Delete a placement group."""
    group = _placement_groups.get(group_id)
    if not group or group["owner_id"] != str(user.id):
        raise HTTPException(status_code=404, detail="Placement group not found")

    del _placement_groups[group_id]
    return {"status": "deleted"}

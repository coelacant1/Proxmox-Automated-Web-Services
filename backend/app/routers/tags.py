"""Resource tagging API - CRUD for user-defined key-value tags on resources."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import Resource, Tag, User

router = APIRouter(prefix="/api/tags", tags=["tags"])

MAX_TAGS_PER_RESOURCE = 50


class TagCreate(BaseModel):
    resource_id: str
    key: str
    value: str = ""


class TagBatch(BaseModel):
    resource_id: str
    tags: dict[str, str]


@router.get("/resource/{resource_id}")
async def list_resource_tags(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List all tags for a resource."""
    await _verify_resource(db, user.id, resource_id)
    result = await db.execute(
        select(Tag).where(Tag.resource_id == uuid.UUID(resource_id)).order_by(Tag.key)
    )
    tags = result.scalars().all()
    return [{"id": str(t.id), "key": t.key, "value": t.value} for t in tags]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_tag(
    body: TagCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Add a tag to a resource."""
    await _verify_resource(db, user.id, body.resource_id)

    count = await db.scalar(
        select(func.count()).select_from(Tag).where(Tag.resource_id == uuid.UUID(body.resource_id))
    )
    if count and count >= MAX_TAGS_PER_RESOURCE:
        raise HTTPException(status_code=429, detail=f"Max {MAX_TAGS_PER_RESOURCE} tags per resource")

    existing = await db.execute(
        select(Tag).where(Tag.resource_id == uuid.UUID(body.resource_id), Tag.key == body.key)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Tag '{body.key}' already exists")

    tag = Tag(owner_id=user.id, resource_id=uuid.UUID(body.resource_id), key=body.key, value=body.value)
    db.add(tag)
    await db.commit()
    return {"id": str(tag.id), "key": tag.key, "value": tag.value}


@router.put("/batch")
async def batch_set_tags(
    body: TagBatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Set multiple tags at once (upsert)."""
    await _verify_resource(db, user.id, body.resource_id)
    rid = uuid.UUID(body.resource_id)

    for key, value in body.tags.items():
        result = await db.execute(select(Tag).where(Tag.resource_id == rid, Tag.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
        else:
            db.add(Tag(owner_id=user.id, resource_id=rid, key=key, value=value))

    await db.commit()
    return {"status": "updated", "count": len(body.tags)}


@router.delete("/{tag_id}")
async def delete_tag(
    tag_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Delete a tag."""
    result = await db.execute(
        select(Tag).where(Tag.id == uuid.UUID(tag_id), Tag.owner_id == user.id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    await db.delete(tag)
    await db.commit()
    return {"status": "deleted"}


@router.delete("/resource/{resource_id}")
async def delete_all_resource_tags(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Delete all tags from a resource."""
    await _verify_resource(db, user.id, resource_id)
    await db.execute(delete(Tag).where(Tag.resource_id == uuid.UUID(resource_id)))
    await db.commit()
    return {"status": "cleared"}


async def _verify_resource(db: AsyncSession, user_id: uuid.UUID, resource_id: str) -> Resource:
    result = await db.execute(
        select(Resource).where(Resource.id == uuid.UUID(resource_id), Resource.owner_id == user_id)
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource

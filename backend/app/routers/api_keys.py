"""API key management endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import User
from app.services.api_key_service import APIKey, create_api_key

router = APIRouter(prefix="/api/keys", tags=["api-keys"])


class APIKeyCreate(BaseModel):
    name: str


class APIKeyRead(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class APIKeyCreated(APIKeyRead):
    raw_key: str  # only returned on creation


@router.post("/", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: APIKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    key_record, raw_key = await create_api_key(db, user.id, body.name)
    return APIKeyCreated(
        id=key_record.id,
        name=key_record.name,
        key_prefix=key_record.key_prefix,
        is_active=key_record.is_active,
        created_at=key_record.created_at,
        last_used_at=key_record.last_used_at,
        raw_key=raw_key,
    )


@router.get("/", response_model=list[APIKeyRead])
async def list_keys(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(APIKey).where(APIKey.user_id == user.id).order_by(APIKey.created_at.desc()))
    return result.scalars().all()


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(APIKey).where(APIKey.id == uuid.UUID(key_id), APIKey.user_id == user.id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    key.is_active = False
    await db.commit()

"""API key management for programmatic access."""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.security import hash_password, verify_password
from app.models.models import GUID


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)  # first 12 chars for display
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)


def generate_api_key() -> str:
    """Generate a paws_xxxx... style API key."""
    return f"paws_{secrets.token_urlsafe(32)}"


async def create_api_key(db: AsyncSession, user_id: uuid.UUID, name: str) -> tuple[APIKey, str]:
    """Create a new API key. Returns (db record, raw key). Raw key is only shown once."""
    raw_key = generate_api_key()
    key_record = APIKey(
        user_id=user_id,
        name=name,
        key_prefix=raw_key[:12],
        key_hash=hash_password(raw_key),
    )
    db.add(key_record)
    await db.commit()
    await db.refresh(key_record)
    return key_record, raw_key


async def verify_api_key(db: AsyncSession, raw_key: str) -> APIKey | None:
    """Look up and verify an API key. Returns the key record if valid."""
    prefix = raw_key[:12]
    result = await db.execute(select(APIKey).where(APIKey.key_prefix == prefix, APIKey.is_active.is_(True)))
    keys = result.scalars().all()
    for key in keys:
        if verify_password(raw_key, key.key_hash):
            key.last_used_at = func.now()
            await db.commit()
            return key
    return None


async def verify_group_api_key(db: AsyncSession, raw_key: str):
    """Look up and verify a group API key. Returns the GroupAPIKey record if valid."""
    from app.models.models import GroupAPIKey

    prefix = raw_key[:12]
    result = await db.execute(
        select(GroupAPIKey).where(GroupAPIKey.key_prefix == prefix, GroupAPIKey.is_active.is_(True))
    )
    keys = result.scalars().all()
    for key in keys:
        if verify_password(raw_key, key.key_hash):
            key.last_used_at = func.now()
            await db.commit()
            return key
    return None


async def create_group_api_key(db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, name: str):
    """Create a group-scoped API key. Returns (GroupAPIKey record, raw key)."""
    from app.models.models import GroupAPIKey

    raw_key = generate_api_key()
    key_record = GroupAPIKey(
        group_id=group_id,
        created_by=user_id,
        name=name,
        key_prefix=raw_key[:12],
        key_hash=hash_password(raw_key),
    )
    db.add(key_record)
    await db.commit()
    await db.refresh(key_record)
    return key_record, raw_key

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.models import User, UserQuota


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_oauth_sub(db: AsyncSession, oauth_sub: str) -> User | None:
    result = await db.execute(select(User).where(User.oauth_sub == oauth_sub))
    return result.scalar_one_or_none()


async def create_local_user(
    db: AsyncSession, email: str, username: str, password: str, full_name: str | None = None
) -> User:
    user = User(
        email=email,
        username=username,
        hashed_password=hash_password(password),
        full_name=full_name,
        auth_provider="local",
    )
    db.add(user)
    await db.flush()
    await _create_default_quota(db, user.id)
    await db.commit()
    await db.refresh(user)
    return user


async def create_oauth_user(
    db: AsyncSession, email: str, username: str, oauth_sub: str, full_name: str | None = None
) -> User:
    user = User(
        email=email,
        username=username,
        oauth_sub=oauth_sub,
        full_name=full_name,
        auth_provider="authentik",
    )
    db.add(user)
    await db.flush()
    await _create_default_quota(db, user.id)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_local_user(db: AsyncSession, username: str, password: str) -> User | None:
    user = await get_user_by_username(db, username)
    if user is None or user.hashed_password is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def _create_default_quota(db: AsyncSession, user_id: uuid.UUID) -> None:
    quota = UserQuota(user_id=user_id)
    db.add(quota)

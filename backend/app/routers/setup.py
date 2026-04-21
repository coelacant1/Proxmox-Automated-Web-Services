"""First-run setup wizard API.

Provides endpoints to check whether the application has been initialized
(i.e. at least one admin user exists) and to create the first admin
account without requiring authentication.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password, validate_password
from app.models.models import SystemSetting, User, UserQuota, UserRole

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupStatus(BaseModel):
    initialized: bool
    platform_name: str


class SetupInit(BaseModel):
    username: str
    email: EmailStr
    password: str
    confirm_password: str
    platform_name: str = "pAWS"


class SetupInitResponse(BaseModel):
    message: str
    username: str


async def _is_initialized(db: AsyncSession) -> bool:
    """Check if at least one admin user exists."""
    result = await db.execute(select(func.count()).select_from(User).where(User.role == UserRole.ADMIN))
    return (result.scalar() or 0) > 0


@router.get("/status", response_model=SetupStatus)
async def get_setup_status(db: AsyncSession = Depends(get_db)):
    """Check if the application has been initialized."""
    initialized = await _is_initialized(db)
    platform_name = "pAWS"
    if initialized:
        result = await db.execute(select(SystemSetting.value).where(SystemSetting.key == "platform_name"))
        row = result.scalar_one_or_none()
        if row:
            platform_name = row
    return SetupStatus(initialized=initialized, platform_name=platform_name)


@router.post(
    "/init",
    response_model=SetupInitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def initialize(body: SetupInit, db: AsyncSession = Depends(get_db)):
    """Create the first admin account and mark the application as initialized.

    This endpoint only works when no admin user exists yet.
    """
    if await _is_initialized(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application is already initialized",
        )

    if body.password != body.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Passwords do not match",
        )

    pwd_error = validate_password(body.password)
    if pwd_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=pwd_error,
        )

    if len(body.username) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username must be at least 3 characters",
        )

    # Create admin user
    admin_user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password),
        full_name="PAWS Administrator",
        role=UserRole.ADMIN,
        is_superuser=True,
        auth_provider="local",
        must_change_password=False,
    )
    db.add(admin_user)
    await db.flush()
    db.add(UserQuota(user_id=admin_user.id))

    # Save platform name
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == "platform_name"))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = body.platform_name
    else:
        db.add(
            SystemSetting(
                key="platform_name",
                value=body.platform_name,
                description="Display name of the platform",
            )
        )

    await db.commit()

    # Clear the setup-required flag so middleware stops blocking
    from app.core.setup_state import mark_initialized

    mark_initialized()

    # Run deferred seeds that were skipped during startup
    from app.main import seed_instance_types, seed_system_settings

    await seed_system_settings()
    await seed_instance_types()

    return SetupInitResponse(
        message="Application initialized successfully",
        username=body.username,
    )

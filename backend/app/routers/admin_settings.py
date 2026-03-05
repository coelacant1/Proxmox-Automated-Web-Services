"""Admin system settings management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.models import SystemSetting, User
from app.schemas.schemas import SystemSettingRead, SystemSettingUpdate

router = APIRouter(prefix="/api/admin/settings", tags=["admin"])


@router.get("/", response_model=list[SystemSettingRead])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all system settings."""
    result = await db.execute(select(SystemSetting).order_by(SystemSetting.key))
    return result.scalars().all()


@router.get("/{key}", response_model=SystemSettingRead)
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    return setting


@router.patch("/{key}", response_model=SystemSettingRead)
async def update_setting(
    key: str,
    data: SystemSettingUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")

    setting.value = data.value
    await db.commit()
    await db.refresh(setting)
    return setting

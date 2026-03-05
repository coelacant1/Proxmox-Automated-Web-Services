"""Storage pool listing for authenticated users."""

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import SystemSetting, User

router = APIRouter(prefix="/api/storage-pools", tags=["storage-pools"])


@router.get("/")
async def list_storage_pools(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    """Return available storage pools and the default."""
    pools_result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "storage_pools")
    )
    default_result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "default_storage_pool")
    )

    pools_setting = pools_result.scalar_one_or_none()
    default_setting = default_result.scalar_one_or_none()

    pools = json.loads(pools_setting.value) if pools_setting else ["local-lvm"]
    default = default_setting.value if default_setting else "local-lvm"

    return {"pools": pools, "default": default}

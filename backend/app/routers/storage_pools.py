"""Storage pool listing for authenticated users."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import SystemSetting, User
from app.services.proxmox_client import proxmox_client

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


@router.get("/available")
async def list_available_storage_pools(
    _: User = Depends(require_admin),
):
    """Admin-only: list all Proxmox storages that can hold VM/container disks."""
    try:
        storages = proxmox_client.get_storage_list()
        result = []
        for s in storages:
            content = s.get("content", "")
            if "images" in content or "rootdir" in content:
                result.append({
                    "storage": s["storage"],
                    "type": s.get("type", ""),
                    "shared": bool(s.get("shared", 0)),
                    "content": content,
                })
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

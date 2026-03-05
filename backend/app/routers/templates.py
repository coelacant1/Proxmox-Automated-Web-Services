"""User-facing template catalog endpoints."""

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import TemplateCatalog, User
from app.schemas.schemas import TemplateCatalogRead

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("/", response_model=list[TemplateCatalogRead])
async def list_templates(
    category: str | None = Query(None, pattern="^(vm|lxc)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    """List active templates available for provisioning."""
    query = select(TemplateCatalog).where(TemplateCatalog.is_active.is_(True)).order_by(TemplateCatalog.name)
    if category:
        query = query.where(TemplateCatalog.category == category)
    result = await db.execute(query)
    templates = result.scalars().all()

    return [
        TemplateCatalogRead(
            id=t.id,
            proxmox_vmid=t.proxmox_vmid,
            name=t.name,
            description=t.description,
            os_type=t.os_type,
            category=t.category,
            min_cpu=t.min_cpu,
            min_ram_mb=t.min_ram_mb,
            min_disk_gb=t.min_disk_gb,
            icon_url=t.icon_url,
            is_active=t.is_active,
            tags=json.loads(t.tags) if t.tags else None,
            created_at=t.created_at,
        )
        for t in templates
    ]

"""Admin template catalog management endpoints."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.models import TemplateCatalog, User
from app.schemas.schemas import TemplateCatalogCreate, TemplateCatalogRead, TemplateCatalogUpdate
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/admin/templates", tags=["admin"])


@router.get("/", response_model=list[TemplateCatalogRead])
async def list_catalog_templates(
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all catalog templates (admin sees inactive too)."""
    query = select(TemplateCatalog).order_by(TemplateCatalog.name)
    if not include_inactive:
        query = query.where(TemplateCatalog.is_active.is_(True))
    result = await db.execute(query)
    templates = result.scalars().all()
    return [_template_to_read(t) for t in templates]


@router.post("/", response_model=TemplateCatalogRead, status_code=status.HTTP_201_CREATED)
async def create_catalog_template(
    data: TemplateCatalogCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Add a Proxmox template to the user-facing catalog."""
    existing = await db.execute(
        select(TemplateCatalog).where(TemplateCatalog.proxmox_vmid == data.proxmox_vmid)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Template with this VMID already in catalog")

    template = TemplateCatalog(
        proxmox_vmid=data.proxmox_vmid,
        name=data.name,
        description=data.description,
        os_type=data.os_type,
        category=data.category,
        min_cpu=data.min_cpu,
        min_ram_mb=data.min_ram_mb,
        min_disk_gb=data.min_disk_gb,
        icon_url=data.icon_url,
        tags=json.dumps(data.tags) if data.tags else None,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return _template_to_read(template)


@router.patch("/{template_id}", response_model=TemplateCatalogRead)
async def update_catalog_template(
    template_id: str,
    data: TemplateCatalogUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(TemplateCatalog).where(TemplateCatalog.id == uuid.UUID(template_id)))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = data.model_dump(exclude_unset=True)
    if "tags" in update_data:
        update_data["tags"] = json.dumps(update_data["tags"]) if update_data["tags"] else None

    for field, value in update_data.items():
        setattr(template, field, value)

    await db.commit()
    await db.refresh(template)
    return _template_to_read(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalog_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(TemplateCatalog).where(TemplateCatalog.id == uuid.UUID(template_id)))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    await db.delete(template)
    await db.commit()


@router.get("/proxmox-available")
async def list_proxmox_templates(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List Proxmox templates with auto-detected type, specs, and OS.

    Filters out templates already in the catalog. Returns enriched data
    so the admin only needs to pick a template and optionally rename it.
    """
    try:
        resources = proxmox_client.get_cluster_resources()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Proxmox: {e}")

    # Get VMIDs already in catalog
    result = await db.execute(select(TemplateCatalog.proxmox_vmid))
    existing_vmids = {row[0] for row in result.all()}

    templates = []
    for r in resources:
        if r.get("template", 0) != 1:
            continue
        vmid = r.get("vmid")
        if vmid in existing_vmids:
            continue

        name = r.get("name", f"template-{vmid}")
        pve_type = r.get("type", "qemu")  # qemu or lxc
        category = "lxc" if pve_type == "lxc" else "vm"
        os_type = _detect_os_type(name)

        templates.append({
            "vmid": vmid,
            "name": name,
            "node": r.get("node"),
            "category": category,
            "os_type": os_type,
            "cpu": r.get("maxcpu", 1),
            "ram_mb": r.get("maxmem", 0) // (1024 * 1024),
            "disk_gb": r.get("maxdisk", 0) // (1024 * 1024 * 1024),
            "tags": r.get("tags", "").split(";") if r.get("tags") else [],
        })

    return sorted(templates, key=lambda t: t["vmid"])


def _detect_os_type(name: str) -> str:
    """Best-effort OS detection from template name."""
    lower = name.lower()
    if any(w in lower for w in ("windows", "win7", "win10", "win11", "w11", "w10")):
        return "windows"
    if any(w in lower for w in ("ubuntu", "debian", "centos", "rhel", "fedora", "kali",
                                 "linux", "alpine", "arch", "suse", "rocky", "alma")):
        return "linux"
    if any(w in lower for w in ("freebsd", "openbsd", "netbsd", "pfsense", "opnsense")):
        return "bsd"
    return "other"


def _template_to_read(t: TemplateCatalog) -> TemplateCatalogRead:
    """Convert model to read schema, parsing JSON tags."""
    return TemplateCatalogRead(
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

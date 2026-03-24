"""Template request endpoints - users request VM-to-template conversion, admin approves."""

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin, require_capability
from app.models.models import Resource, TemplateCatalog, TemplateRequest, User
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/templates", tags=["template-requests"])


class TemplateRequestCreate(BaseModel):
    resource_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category: str = "vm"
    os_type: str | None = None
    min_cpu: int = 1
    min_ram_mb: int = 512
    min_disk_gb: int = 10
    tags: list[str] | None = None
    icon_url: str | None = None


class TemplateRequestReview(BaseModel):
    status: str  # approved, rejected
    admin_notes: str | None = None


# --- User endpoints ---


@router.post("/request", status_code=201)
async def submit_template_request(
    body: TemplateRequestCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_capability("template.request")),
):
    # Verify resource exists and user owns it
    result = await db.execute(select(Resource).where(Resource.id == body.resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(404, "Resource not found")
    if resource.owner_id != user.id:
        raise HTTPException(403, "You can only request templates from your own resources")
    if resource.resource_type not in ("vm", "lxc"):
        raise HTTPException(400, "Only VMs and containers can be converted to templates")

    # Check no pending request for same resource
    existing = await db.execute(
        select(TemplateRequest).where(
            TemplateRequest.resource_id == body.resource_id,
            TemplateRequest.status == "pending",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "A pending template request already exists for this resource")

    req = TemplateRequest(
        user_id=user.id,
        resource_id=body.resource_id,
        name=body.name,
        description=body.description,
        category=body.category,
        os_type=body.os_type,
        min_cpu=body.min_cpu,
        min_ram_mb=body.min_ram_mb,
        min_disk_gb=body.min_disk_gb,
        tags=json.dumps(body.tags) if body.tags else None,
        icon_url=body.icon_url,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return _request_dict(req)


@router.get("/requests/mine")
async def my_template_requests(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(TemplateRequest).where(TemplateRequest.user_id == user.id).order_by(TemplateRequest.created_at.desc())
    )
    return [_request_dict(r) for r in result.scalars().all()]


# --- Admin endpoints ---


@router.get("/requests")
async def admin_list_requests(
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = select(TemplateRequest).order_by(TemplateRequest.created_at.desc())
    if status_filter:
        query = query.where(TemplateRequest.status == status_filter)
    result = await db.execute(query)
    return [_request_dict(r) for r in result.scalars().all()]


@router.patch("/requests/{request_id}")
async def review_template_request(
    request_id: uuid.UUID,
    body: TemplateRequestReview,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if body.status not in ("approved", "rejected"):
        raise HTTPException(400, "status must be 'approved' or 'rejected'")

    result = await db.execute(select(TemplateRequest).where(TemplateRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(404, "Template request not found")
    if req.status != "pending":
        raise HTTPException(400, f"Request is already {req.status}")

    req.admin_notes = body.admin_notes
    req.reviewed_by = admin.id
    req.reviewed_at = datetime.now(UTC)

    if body.status == "rejected":
        req.status = "rejected"
        await db.commit()
        await db.refresh(req)
        return _request_dict(req)

    # Approved - convert VM to template on PVE
    resource = req.resource
    if not resource or not resource.proxmox_vmid or not resource.proxmox_node:
        req.status = "failed"
        req.admin_notes = (body.admin_notes or "") + "\nResource missing VMID or node."
        await db.commit()
        await db.refresh(req)
        return _request_dict(req)

    req.status = "converting"
    await db.commit()

    try:
        # Stop VM if running
        try:
            vm_status = proxmox_client.get_vm_status(resource.proxmox_node, resource.proxmox_vmid)
            if vm_status.get("status") == "running":
                proxmox_client.shutdown_vm(resource.proxmox_node, resource.proxmox_vmid)
                proxmox_client.wait_for_task(
                    resource.proxmox_node,
                    proxmox_client.shutdown_vm(resource.proxmox_node, resource.proxmox_vmid),
                    timeout=60,
                )
        except Exception:
            pass

        # Convert to template
        proxmox_client.api.nodes(resource.proxmox_node).qemu(resource.proxmox_vmid).template.post()

        # Create catalog entry
        tags_list = json.loads(req.tags) if req.tags else None
        catalog = TemplateCatalog(
            proxmox_vmid=resource.proxmox_vmid,
            name=req.name,
            description=req.description,
            os_type=req.os_type,
            category=req.category,
            min_cpu=req.min_cpu,
            min_ram_mb=req.min_ram_mb,
            min_disk_gb=req.min_disk_gb,
            icon_url=req.icon_url,
            tags=json.dumps(tags_list) if tags_list else None,
            is_active=True,
        )
        db.add(catalog)

        # Remove from user's resources
        await db.delete(resource)

        req.status = "completed"
        await db.commit()
        await db.refresh(req)
        return _request_dict(req)

    except Exception as e:
        req.status = "failed"
        req.admin_notes = (body.admin_notes or "") + f"\nConversion failed: {e}"
        await db.commit()
        await db.refresh(req)
        return _request_dict(req)


def _request_dict(r: TemplateRequest) -> dict:
    return {
        "id": str(r.id),
        "user_id": str(r.user_id),
        "username": r.user.username if r.user else None,
        "resource_id": str(r.resource_id),
        "resource_name": r.resource.display_name if r.resource else None,
        "resource_vmid": r.resource.proxmox_vmid if r.resource else None,
        "name": r.name,
        "description": r.description,
        "category": r.category,
        "os_type": r.os_type,
        "min_cpu": r.min_cpu,
        "min_ram_mb": r.min_ram_mb,
        "min_disk_gb": r.min_disk_gb,
        "tags": json.loads(r.tags) if r.tags else [],
        "icon_url": r.icon_url,
        "status": r.status,
        "admin_notes": r.admin_notes,
        "reviewed_by": str(r.reviewed_by) if r.reviewed_by else None,
        "reviewer_name": r.reviewer.username if r.reviewer else None,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }

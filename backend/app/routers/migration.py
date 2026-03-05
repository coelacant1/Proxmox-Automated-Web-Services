"""VM import/export API - migration tools for moving VMs between environments."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import Resource, User
from app.services.audit_service import log_action
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/migration", tags=["migration"])


class ExportRequest(BaseModel):
    storage: str = "local"
    compress: str = "zstd"  # none, lzo, gzip, zstd
    mode: str = "snapshot"  # snapshot, suspend, stop


class ImportRequest(BaseModel):
    name: str
    source_node: str
    source_vmid: int
    target_node: str | None = None
    target_storage: str = "local"


class CloneRequest(BaseModel):
    name: str
    target_node: str | None = None
    full_clone: bool = True


@router.post("/{resource_id}/export")
async def export_vm(
    resource_id: str,
    body: ExportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Export a VM/container as a backup file for migration."""
    resource = await _get_user_resource(db, user.id, resource_id)

    if body.compress not in ("none", "lzo", "gzip", "zstd"):
        raise HTTPException(status_code=400, detail="Compress must be: none, lzo, gzip, zstd")
    if body.mode not in ("snapshot", "suspend", "stop"):
        raise HTTPException(status_code=400, detail="Mode must be: snapshot, suspend, stop")

    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
    try:
        task = proxmox_client.create_backup(
            resource.proxmox_node,
            resource.proxmox_vmid,
            storage=body.storage,
            compress=body.compress,
            mode=body.mode,
        )
        await log_action(db, user.id, "vm_export", resource.resource_type, resource.id)
        return {
            "status": "export_started",
            "resource_id": str(resource.id),
            "vmtype": vmtype,
            "task_id": task,
            "storage": body.storage,
            "compress": body.compress,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{resource_id}/clone", status_code=status.HTTP_202_ACCEPTED)
async def clone_vm(
    resource_id: str,
    body: CloneRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Clone a VM/container to create an identical copy."""
    resource = await _get_user_resource(db, user.id, resource_id)

    target_node = body.target_node or resource.proxmox_node
    new_vmid = proxmox_client.get_next_vmid()

    try:
        task = proxmox_client.clone_vm(
            resource.proxmox_node,
            resource.proxmox_vmid,
            new_vmid,
            name=body.name,
            target=target_node,
            full=body.full_clone,
        )

        new_resource = Resource(
            id=uuid.uuid4(),
            owner_id=user.id,
            resource_type=resource.resource_type,
            display_name=body.name,
            proxmox_vmid=new_vmid,
            proxmox_node=target_node,
            status="creating",
            specs=resource.specs,
        )
        db.add(new_resource)
        await db.commit()
        await log_action(db, user.id, "vm_clone", resource.resource_type, new_resource.id)

        return {
            "status": "clone_started",
            "source_id": str(resource.id),
            "new_id": str(new_resource.id),
            "new_vmid": new_vmid,
            "task_id": task,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{resource_id}/convert-template")
async def convert_to_template(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Convert a stopped VM into a template for cloning."""
    resource = await _get_user_resource(db, user.id, resource_id)

    if resource.status not in ("stopped", "created"):
        raise HTTPException(status_code=409, detail="VM must be stopped to convert to template")

    try:
        proxmox_client.convert_to_template(resource.proxmox_node, resource.proxmox_vmid)
        resource.status = "template"
        await db.commit()
        await log_action(db, user.id, "vm_convert_template", resource.resource_type, resource.id)
        return {"status": "converted", "resource_id": str(resource.id)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{resource_id}/export-status")
async def get_export_status(
    resource_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Check the status of an export/backup task."""
    resource = await _get_user_resource(db, user.id, resource_id)

    try:
        status_data = proxmox_client.get_task_status(resource.proxmox_node, task_id)
        return {
            "resource_id": str(resource.id),
            "task_id": task_id,
            "status": status_data.get("status"),
            "exit_status": status_data.get("exitstatus"),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Helpers ---


async def _get_user_resource(db: AsyncSession, user_id: uuid.UUID, resource_id: str) -> Resource:
    result = await db.execute(
        select(Resource).where(
            Resource.id == uuid.UUID(resource_id),
            Resource.owner_id == user_id,
            Resource.status != "destroyed",
        )
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource

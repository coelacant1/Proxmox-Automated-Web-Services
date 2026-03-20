"""Volume management - create, list, attach, detach, resize, delete.

Volumes are additional SCSI disks created on Proxmox storage and attached
to virtual machines.  They can be detached and re-attached to other VMs.
"""

import json
import logging
import re
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.core.pagination import MessageResponse
from app.models.models import Resource, SystemSetting, User, Volume
from app.schemas.schemas import VolumeAttachRequest, VolumeCreate, VolumeRead
from app.services.proxmox_client import ProxmoxClient

router = APIRouter(prefix="/api/volumes", tags=["volumes"])
log = logging.getLogger(__name__)


class VolumeResizeRequest(BaseModel):
    size_gib: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_proxmox() -> ProxmoxClient:
    return ProxmoxClient()


def _next_scsi_slot(config: dict) -> str:
    """Find the next available SCSI slot (scsi1 .. scsi13) on a VM."""
    used = {k for k in config if re.match(r"^scsi\d+$", k)}
    for i in range(1, 14):  # scsi0 is typically the boot disk
        slot = f"scsi{i}"
        if slot not in used:
            return slot
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="No available SCSI slots on this VM (max 13 additional disks)",
    )


def _find_unused_slot(config: dict, volid: str) -> str | None:
    """Find the unusedN slot holding a specific volid in a VM config."""
    for key, val in config.items():
        if key.startswith("unused"):
            # Config values may include params: "rbd:vm-100-disk-1,size=10G"
            config_volid = str(val).split(",")[0]
            if config_volid == volid:
                return key
    return None


def _parse_volid_from_config(config: dict, slot: str) -> str | None:
    """Extract the volume identifier from a disk config value."""
    val = config.get(slot, "")
    if not val:
        return None
    # Format: "storage:volname,size=10G,..." -> "storage:volname"
    return str(val).split(",")[0]


async def _get_vm_resource(
    db: AsyncSession, resource_id: str, owner_id
) -> Resource:
    """Fetch a VM resource owned by the user, raising 404 if missing."""
    result = await db.execute(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.owner_id == owner_id,
            Resource.resource_type == "vm",
        )
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VM not found or not owned by you",
        )
    return resource


async def _get_user_volume(
    db: AsyncSession, user_id: _uuid.UUID, volume_id: str, min_perm: str = "read",
) -> Volume:
    """Get a volume by ownership or group share."""
    vid = _uuid.UUID(volume_id) if isinstance(volume_id, str) else volume_id
    result = await db.execute(select(Volume).where(Volume.id == vid, Volume.owner_id == user_id))
    vol = result.scalar_one_or_none()
    if not vol:
        from app.services.group_access import check_group_access
        res2 = await db.execute(select(Volume).where(Volume.id == vid))
        vol = res2.scalar_one_or_none()
        if vol and not await check_group_access(db, user_id, "volume", vid, min_perm):
            vol = None
    if not vol:
        raise HTTPException(status_code=404, detail="Volume not found")
    return vol


def _enrich_volume(vol: Volume, db_resources: dict | None = None) -> dict:
    """Convert a Volume ORM object to a dict with display_name added."""
    data = {
        "id": vol.id,
        "name": vol.name,
        "size_gib": vol.size_gib,
        "storage_pool": vol.storage_pool,
        "status": vol.status,
        "resource_id": vol.resource_id,
        "disk_slot": vol.disk_slot,
        "proxmox_node": vol.proxmox_node,
        "proxmox_volid": vol.proxmox_volid,
        "proxmox_owner_vmid": vol.proxmox_owner_vmid,
        "display_name": None,
        "created_at": vol.created_at,
    }
    if vol.resource_id and db_resources:
        res = db_resources.get(str(vol.resource_id))
        if res:
            data["display_name"] = res.display_name
    return data


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/")
async def list_volumes(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    resource_id: str | None = None,
):
    query = select(Volume).where(Volume.owner_id == user.id)
    if resource_id:
        query = query.where(Volume.resource_id == resource_id)
    query = query.order_by(Volume.created_at.desc())
    result = await db.execute(query)
    volumes = list(result.scalars().all())

    # Bulk-load resource names for display
    res_ids = {str(v.resource_id) for v in volumes if v.resource_id}
    db_resources: dict = {}
    if res_ids:
        res_result = await db.execute(select(Resource).where(Resource.id.in_(res_ids)))
        for r in res_result.scalars().all():
            db_resources[str(r.id)] = r

    return [_enrich_volume(v, db_resources) for v in volumes]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_volume(
    body: VolumeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Create a new disk and attach it to the specified VM."""

    if body.size_gib < 1 or body.size_gib > 10000:
        raise HTTPException(status_code=422, detail="Size must be 1-10000 GiB")

    # Validate storage pool
    pools_result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "storage_pools")
    )
    pools_setting = pools_result.scalar_one_or_none()
    allowed = json.loads(pools_setting.value) if pools_setting else ["local-lvm"]
    if body.storage_pool not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Storage pool '{body.storage_pool}' is not enabled by the administrator",
        )

    # Get the target VM
    resource = await _get_vm_resource(db, str(body.resource_id), user.id)
    if not resource.proxmox_vmid or not resource.proxmox_node:
        raise HTTPException(status_code=400, detail="VM has no Proxmox assignment yet")

    pve = _get_proxmox()
    node = resource.proxmox_node
    vmid = resource.proxmox_vmid

    # Find next available SCSI slot
    config = pve.get_vm_config(node, vmid)
    slot = _next_scsi_slot(config)

    # Create and attach disk in one PVE call
    try:
        pve.update_vm_config(node, vmid, **{slot: f"{body.storage_pool}:{body.size_gib}"})
    except Exception as exc:
        log.error("Failed to create disk on PVE: %s", exc)
        raise HTTPException(status_code=502, detail=f"Proxmox error: {exc}") from exc

    # Read back config to get the actual volid
    config = pve.get_vm_config(node, vmid)
    volid = _parse_volid_from_config(config, slot)

    vol = Volume(
        owner_id=user.id,
        name=body.name,
        size_gib=body.size_gib,
        storage_pool=body.storage_pool,
        status="attached",
        resource_id=resource.id,
        disk_slot=slot,
        proxmox_node=node,
        proxmox_volid=volid,
        proxmox_owner_vmid=vmid,
    )
    db.add(vol)
    await db.commit()
    await db.refresh(vol)
    return _enrich_volume(vol, {str(resource.id): resource})


@router.get("/{volume_id}")
async def get_volume(
    volume_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vol = await _get_user_volume(db, user.id, volume_id)
    return _enrich_volume(vol)


@router.post("/{volume_id}/detach", response_model=MessageResponse)
async def detach_volume(
    volume_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Detach disk from VM. Disk stays on storage as an unused volume."""
    vol = await _get_user_volume(db, user.id, volume_id, min_perm="admin")
    if not vol:
        raise HTTPException(status_code=404, detail="Volume not found")
    if vol.status != "attached" or not vol.disk_slot:
        raise HTTPException(status_code=400, detail="Volume is not attached")

    resource = None
    if vol.resource_id:
        res_result = await db.execute(select(Resource).where(Resource.id == vol.resource_id))
        resource = res_result.scalar_one_or_none()

    if not resource or not resource.proxmox_node or not resource.proxmox_vmid:
        raise HTTPException(status_code=400, detail="Cannot find the VM this volume is attached to")

    pve = _get_proxmox()
    node = resource.proxmox_node
    vmid = resource.proxmox_vmid

    try:
        # Remove disk from VM config (becomes unusedN)
        pve.update_vm_config(node, vmid, delete=vol.disk_slot)
    except Exception as exc:
        log.error("Failed to detach disk on PVE: %s", exc)
        raise HTTPException(status_code=502, detail=f"Proxmox error: {exc}") from exc

    # Verify the disk was preserved as unused and update stored volid
    try:
        updated_config = pve.get_vm_config(node, vmid)
        unused_slot = _find_unused_slot(updated_config, vol.proxmox_volid) if vol.proxmox_volid else None
        if not unused_slot:
            log.warning(
                "Volume %s (volid=%s) not found in unused slots after detach. "
                "Disk may have been removed by storage backend.",
                vol.id, vol.proxmox_volid,
            )
    except Exception:
        pass

    vol.resource_id = None
    vol.disk_slot = None
    vol.status = "available"
    # Keep proxmox_owner_vmid so we know where the unused disk lives
    await db.commit()
    return MessageResponse(status="ok", message="Volume detached")


@router.post("/{volume_id}/attach", response_model=MessageResponse)
async def attach_volume(
    volume_id: str,
    body: VolumeAttachRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Attach an available volume to a VM."""
    vol = await _get_user_volume(db, user.id, volume_id, min_perm="admin")
    if vol.status != "available":
        raise HTTPException(status_code=400, detail="Volume is not available for attachment")
    if not vol.proxmox_volid or not vol.proxmox_owner_vmid:
        raise HTTPException(status_code=400, detail="Volume has no Proxmox disk allocated")

    # Get target VM
    target = await _get_vm_resource(db, str(body.resource_id), user.id)
    if not target.proxmox_vmid or not target.proxmox_node:
        raise HTTPException(status_code=400, detail="Target VM has no Proxmox assignment")

    pve = _get_proxmox()
    target_node = target.proxmox_node
    target_vmid = target.proxmox_vmid

    # Find next available SCSI slot on target
    target_config = pve.get_vm_config(target_node, target_vmid)
    slot = _next_scsi_slot(target_config)

    try:
        if target_vmid == vol.proxmox_owner_vmid:
            # Re-attaching to the same VM - find unused slot and promote
            unused_slot = _find_unused_slot(target_config, vol.proxmox_volid)
            if unused_slot:
                pve.update_vm_config(
                    target_node, target_vmid,
                    **{slot: vol.proxmox_volid, "delete": unused_slot},
                )
            else:
                # Unused entry may not exist; try direct reference
                pve.update_vm_config(target_node, target_vmid, **{slot: vol.proxmox_volid})
        else:
            # Different VM - use direct volid reference on shared storage.
            # move_disk requires same-node and often fails cross-node,
            # so we always use direct reference for simplicity.
            pve.update_vm_config(target_node, target_vmid, **{slot: vol.proxmox_volid})

            # Best-effort cleanup: remove stale unused entry from source VM
            source_node = vol.proxmox_node or target_node
            source_vmid = vol.proxmox_owner_vmid
            try:
                source_config = pve.get_vm_config(source_node, source_vmid)
                unused_slot = _find_unused_slot(source_config, vol.proxmox_volid)
                if unused_slot:
                    # Safe to delete unused because the disk is now
                    # actively referenced by the target VM
                    pve.update_vm_config(source_node, source_vmid, delete=unused_slot)
            except Exception:
                pass  # Non-critical cleanup

            vol.proxmox_owner_vmid = target_vmid
            # Volid may have been updated by PVE
            try:
                new_config = pve.get_vm_config(target_node, target_vmid)
                new_volid = _parse_volid_from_config(new_config, slot)
                if new_volid:
                    vol.proxmox_volid = new_volid
            except Exception:
                pass

    except HTTPException:
        raise
    except Exception as exc:
        log.error("Failed to attach disk on PVE: %s", exc)
        raise HTTPException(status_code=502, detail=f"Proxmox error: {exc}") from exc

    vol.resource_id = target.id
    vol.disk_slot = slot
    vol.proxmox_node = target_node
    vol.status = "attached"
    if target_vmid != vol.proxmox_owner_vmid:
        vol.proxmox_owner_vmid = target_vmid
    await db.commit()
    return MessageResponse(status="ok", message=f"Volume attached to {target.display_name} as {slot}")


@router.delete("/{volume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_volume(
    volume_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vol = await _get_user_volume(db, user.id, volume_id, min_perm="admin")
    if vol.status == "attached":
        raise HTTPException(status_code=400, detail="Detach volume before deleting")

    # Delete from Proxmox storage
    if vol.proxmox_volid and vol.proxmox_owner_vmid:
        pve = _get_proxmox()
        node = vol.proxmox_node
        vmid = vol.proxmox_owner_vmid

        # First remove unused entry from VM config if it exists
        if node:
            try:
                config = pve.get_vm_config(node, vmid)
                unused_slot = _find_unused_slot(config, vol.proxmox_volid)
                if unused_slot:
                    pve.update_vm_config(node, vmid, delete=unused_slot)
            except Exception:
                pass

        # Delete the actual disk data from storage
        try:
            storage = vol.storage_pool
            if node:
                pve.delete_storage_content(node, storage, vol.proxmox_volid)
        except Exception as exc:
            log.warning("Failed to delete disk from PVE storage: %s", exc)

    await db.delete(vol)
    await db.commit()


@router.post("/{volume_id}/resize", response_model=MessageResponse)
async def resize_volume(
    volume_id: str,
    body: VolumeResizeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vol = await _get_user_volume(db, user.id, volume_id, min_perm="admin")
    if vol.status != "attached" or not vol.disk_slot:
        raise HTTPException(status_code=400, detail="Volume must be attached to a VM to resize")
    if body.size_gib <= vol.size_gib:
        raise HTTPException(status_code=400, detail="New size must be larger than current size")
    if body.size_gib > 10000:
        raise HTTPException(status_code=422, detail="Maximum volume size is 10000 GiB")

    resource = None
    if vol.resource_id:
        res_result = await db.execute(select(Resource).where(Resource.id == vol.resource_id))
        resource = res_result.scalar_one_or_none()

    if not resource or not resource.proxmox_node or not resource.proxmox_vmid:
        raise HTTPException(status_code=400, detail="Cannot find the VM this volume is attached to")

    grow_by = body.size_gib - vol.size_gib
    pve = _get_proxmox()
    try:
        pve.resize_vm_disk(resource.proxmox_node, resource.proxmox_vmid, vol.disk_slot, f"+{grow_by}G")
    except Exception as exc:
        log.error("Failed to resize disk on PVE: %s", exc)
        raise HTTPException(status_code=502, detail=f"Proxmox error: {exc}") from exc

    vol.size_gib = body.size_gib
    await db.commit()
    return MessageResponse(status="ok", message=f"Volume resized to {body.size_gib} GiB")

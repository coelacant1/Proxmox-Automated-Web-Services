"""Volume management - create, list, attach, detach, resize, snapshot, delete."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.core.pagination import MessageResponse
from app.models.models import Resource, User, Volume
from app.schemas.schemas import VolumeCreate, VolumeRead

router = APIRouter(prefix="/api/volumes", tags=["volumes"])


class VolumeResizeRequest(BaseModel):
    size_gib: int


class VolumeSnapshotRequest(BaseModel):
    name: str


@router.get("/", response_model=list[VolumeRead])
async def list_volumes(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(Volume).where(Volume.owner_id == user.id).order_by(Volume.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/", response_model=VolumeRead, status_code=status.HTTP_201_CREATED)
async def create_volume(
    body: VolumeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    if body.size_gib < 1 or body.size_gib > 10000:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Size must be 1-10000 GiB")

    vol = Volume(owner_id=user.id, name=body.name, size_gib=body.size_gib, storage_pool=body.storage_pool)
    db.add(vol)
    await db.commit()
    await db.refresh(vol)
    return vol


@router.get("/{volume_id}", response_model=VolumeRead)
async def get_volume(
    volume_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(Volume).where(Volume.id == volume_id, Volume.owner_id == user.id))
    vol = result.scalar_one_or_none()
    if not vol:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Volume not found")
    return vol


@router.post("/{volume_id}/attach", response_model=MessageResponse)
async def attach_volume(
    volume_id: str,
    resource_id: str,
    disk_slot: str = "scsi1",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vol_result = await db.execute(select(Volume).where(Volume.id == volume_id, Volume.owner_id == user.id))
    vol = vol_result.scalar_one_or_none()
    if not vol:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Volume not found")
    if vol.status != "available":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Volume is not available for attachment")

    res_result = await db.execute(select(Resource).where(Resource.id == resource_id, Resource.owner_id == user.id))
    resource = res_result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    vol.resource_id = resource.id
    vol.disk_slot = disk_slot
    vol.status = "attached"
    vol.proxmox_node = resource.proxmox_node
    await db.commit()
    return MessageResponse(status="ok", message=f"Volume attached to {resource.display_name} as {disk_slot}")


@router.post("/{volume_id}/detach", response_model=MessageResponse)
async def detach_volume(
    volume_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vol_result = await db.execute(select(Volume).where(Volume.id == volume_id, Volume.owner_id == user.id))
    vol = vol_result.scalar_one_or_none()
    if not vol:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Volume not found")
    if vol.status != "attached":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Volume is not attached")

    vol.resource_id = None
    vol.disk_slot = None
    vol.status = "available"
    await db.commit()
    return MessageResponse(status="ok", message="Volume detached")


@router.delete("/{volume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_volume(
    volume_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vol_result = await db.execute(select(Volume).where(Volume.id == volume_id, Volume.owner_id == user.id))
    vol = vol_result.scalar_one_or_none()
    if not vol:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Volume not found")
    if vol.status == "attached":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Detach volume before deleting")

    await db.delete(vol)
    await db.commit()


@router.post("/{volume_id}/resize", response_model=MessageResponse)
async def resize_volume(
    volume_id: str,
    body: VolumeResizeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vol_result = await db.execute(select(Volume).where(Volume.id == volume_id, Volume.owner_id == user.id))
    vol = vol_result.scalar_one_or_none()
    if not vol:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Volume not found")
    if body.size_gib <= vol.size_gib:
        raise HTTPException(status_code=400, detail="New size must be larger than current size (volumes can only grow)")
    if body.size_gib > 10000:
        raise HTTPException(status_code=422, detail="Maximum volume size is 10000 GiB")

    vol.size_gib = body.size_gib
    await db.commit()
    return MessageResponse(status="ok", message=f"Volume resized to {body.size_gib} GiB")


@router.post("/{volume_id}/snapshot", response_model=MessageResponse)
async def create_volume_snapshot(
    volume_id: str,
    body: VolumeSnapshotRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vol_result = await db.execute(select(Volume).where(Volume.id == volume_id, Volume.owner_id == user.id))
    vol = vol_result.scalar_one_or_none()
    if not vol:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Volume not found")
    # In production, this would create a ZFS/Ceph snapshot
    return MessageResponse(status="ok", message=f"Snapshot '{body.name}' created for volume '{vol.name}'")

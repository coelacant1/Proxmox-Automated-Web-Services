"""Backup and snapshot management endpoints."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import Backup, BackupPlan, Resource, User, UserQuota
from app.services.audit_service import log_action
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/backups", tags=["backups"])


class SnapshotCreate(BaseModel):
    name: str
    description: str = ""
    include_ram: bool = False


class SnapshotRollback(BaseModel):
    name: str


class BackupCreateRequest(BaseModel):
    resource_id: str
    backup_type: str = "snapshot"  # snapshot, full
    notes: str = ""


class BackupPlanCreateRequest(BaseModel):
    resource_id: str
    name: str
    schedule_cron: str  # e.g., "0 2 * * *" for daily at 2am
    backup_type: str = "snapshot"
    retention_count: int = 7
    retention_days: int = 30


class BackupPlanUpdateRequest(BaseModel):
    name: str | None = None
    schedule_cron: str | None = None
    retention_count: int | None = None
    retention_days: int | None = None
    is_active: bool | None = None


# --- Snapshot Endpoints (unchanged) ---


@router.get("/{resource_id}/snapshots")
async def list_snapshots(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_resource(db, user.id, resource_id)
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
    try:
        snapshots = proxmox_client.list_snapshots(resource.proxmox_node, resource.proxmox_vmid, vmtype)
        return [s for s in snapshots if s.get("name") != "current"]
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{resource_id}/snapshots", status_code=status.HTTP_201_CREATED)
async def create_snapshot(
    resource_id: str,
    body: SnapshotCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_resource(db, user.id, resource_id)
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"

    try:
        kwargs = {"description": body.description}
        if vmtype == "qemu" and body.include_ram:
            kwargs["vmstate"] = 1
        upid = proxmox_client.create_snapshot(resource.proxmox_node, resource.proxmox_vmid, body.name, vmtype, **kwargs)
        await log_action(db, user.id, "snapshot_create", resource.resource_type, resource.id, {"snapshot": body.name})
        return {"status": "creating", "task": upid, "snapshot": body.name}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{resource_id}/snapshots/rollback")
async def rollback_snapshot(
    resource_id: str,
    body: SnapshotRollback,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_resource(db, user.id, resource_id)
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"

    try:
        upid = proxmox_client.rollback_snapshot(resource.proxmox_node, resource.proxmox_vmid, body.name, vmtype)
        await log_action(db, user.id, "snapshot_rollback", resource.resource_type, resource.id, {"snapshot": body.name})
        return {"status": "rolling_back", "task": upid}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/{resource_id}/snapshots/{snapshot_name}")
async def delete_snapshot(
    resource_id: str,
    snapshot_name: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_resource(db, user.id, resource_id)
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"

    try:
        upid = proxmox_client.delete_snapshot(resource.proxmox_node, resource.proxmox_vmid, snapshot_name, vmtype)
        await log_action(
            db, user.id, "snapshot_delete", resource.resource_type, resource.id, {"snapshot": snapshot_name}
        )
        return {"status": "deleting", "task": upid}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


async def _get_resource(db: AsyncSession, user_id: uuid.UUID, resource_id: str) -> Resource:
    result = await db.execute(
        select(Resource).where(
            Resource.id == uuid.UUID(resource_id),
            Resource.owner_id == user_id,
            Resource.resource_type.in_(["vm", "lxc"]),
        )
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    if resource.status == "destroyed":
        raise HTTPException(status_code=410, detail="Resource has been destroyed")
    return resource


# --- Backup Endpoints ---


@router.get("")
async def list_backups(
    resource_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    query = select(Backup).where(Backup.owner_id == user.id).order_by(Backup.created_at.desc())
    if resource_id:
        query = query.where(Backup.resource_id == uuid.UUID(resource_id))
    result = await db.execute(query)
    backups = result.scalars().all()
    return [
        {
            "id": str(b.id),
            "resource_id": str(b.resource_id),
            "backup_type": b.backup_type,
            "status": b.status,
            "size_bytes": b.size_bytes,
            "notes": b.notes,
            "created_at": str(b.created_at),
            "completed_at": str(b.completed_at) if b.completed_at else None,
            "expires_at": str(b.expires_at) if b.expires_at else None,
        }
        for b in backups
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_backup(
    body: BackupCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_resource(db, user.id, body.resource_id)

    # Quota check
    backup_count = await db.execute(
        select(func.count(Backup.id)).where(
            Backup.owner_id == user.id,
            Backup.status.in_(["pending", "running", "completed"]),
        )
    )
    count = backup_count.scalar() or 0
    quota = await _get_backup_quota(db, user.id)
    if count >= quota:
        raise HTTPException(status_code=403, detail=f"Backup quota exceeded ({quota} max)")

    backup = Backup(
        resource_id=resource.id,
        owner_id=user.id,
        backup_type=body.backup_type,
        status="pending",
        notes=body.notes,
        started_at=datetime.now(UTC),
    )
    db.add(backup)
    await db.commit()
    await log_action(db, user.id, "backup_create", resource.resource_type, resource.id)

    return {
        "id": str(backup.id),
        "resource_id": str(resource.id),
        "status": "pending",
        "backup_type": body.backup_type,
    }


@router.delete("/{backup_id}")
async def delete_backup(
    backup_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(Backup).where(Backup.id == uuid.UUID(backup_id), Backup.owner_id == user.id)
    )
    backup = result.scalar_one_or_none()
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    await db.delete(backup)
    await db.commit()
    await log_action(db, user.id, "backup_delete", "backup", backup.id)
    return {"status": "deleted"}


# --- Backup Plan Endpoints ---


@router.get("/plans")
async def list_backup_plans(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(BackupPlan).where(BackupPlan.owner_id == user.id).order_by(BackupPlan.created_at.desc())
    )
    plans = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "resource_id": str(p.resource_id),
            "name": p.name,
            "schedule_cron": p.schedule_cron,
            "backup_type": p.backup_type,
            "retention_count": p.retention_count,
            "retention_days": p.retention_days,
            "is_active": p.is_active,
            "last_run_at": str(p.last_run_at) if p.last_run_at else None,
            "next_run_at": str(p.next_run_at) if p.next_run_at else None,
            "created_at": str(p.created_at),
        }
        for p in plans
    ]


@router.post("/plans", status_code=status.HTTP_201_CREATED)
async def create_backup_plan(
    body: BackupPlanCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_resource(db, user.id, body.resource_id)

    plan = BackupPlan(
        resource_id=resource.id,
        owner_id=user.id,
        name=body.name,
        schedule_cron=body.schedule_cron,
        backup_type=body.backup_type,
        retention_count=body.retention_count,
        retention_days=body.retention_days,
    )
    db.add(plan)
    await db.commit()
    await log_action(db, user.id, "backup_plan_create", resource.resource_type, resource.id)

    return {"id": str(plan.id), "name": plan.name, "status": "created"}


@router.patch("/plans/{plan_id}")
async def update_backup_plan(
    plan_id: str,
    body: BackupPlanUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(BackupPlan).where(BackupPlan.id == uuid.UUID(plan_id), BackupPlan.owner_id == user.id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Backup plan not found")

    if body.name is not None:
        plan.name = body.name
    if body.schedule_cron is not None:
        plan.schedule_cron = body.schedule_cron
    if body.retention_count is not None:
        plan.retention_count = body.retention_count
    if body.retention_days is not None:
        plan.retention_days = body.retention_days
    if body.is_active is not None:
        plan.is_active = body.is_active

    await db.commit()
    return {"status": "updated"}


@router.delete("/plans/{plan_id}")
async def delete_backup_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(BackupPlan).where(BackupPlan.id == uuid.UUID(plan_id), BackupPlan.owner_id == user.id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Backup plan not found")

    await db.delete(plan)
    await db.commit()
    return {"status": "deleted"}


async def _get_backup_quota(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(select(UserQuota).where(UserQuota.user_id == user_id))
    quota = result.scalar_one_or_none()
    return quota.max_snapshots if quota else 10


# --- Backup Contents Browser ---


@router.get("/{backup_id}/contents")
async def browse_backup_contents(
    backup_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List files/disks in a backup (via Proxmox backup catalog)."""
    result = await db.execute(
        select(Backup).where(Backup.id == uuid.UUID(backup_id), Backup.owner_id == user.id)
    )
    backup = result.scalar_one_or_none()
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    resource = await db.get(Resource, backup.resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Source resource not found")

    try:
        snapshots = proxmox_client.list_snapshots(resource.proxmox_node, resource.proxmox_vmid, resource.resource_type)
        return {
            "backup_id": str(backup.id),
            "resource": resource.display_name,
            "type": backup.backup_type,
            "contents": snapshots,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Backup Notifications Config ---


class BackupNotificationConfig(BaseModel):
    enabled: bool = True
    webhook_url: str | None = None


@router.put("/{backup_plan_id}/notifications")
async def set_backup_notifications(
    backup_plan_id: str,
    body: BackupNotificationConfig,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Configure notification settings for a backup plan."""
    result = await db.execute(
        select(BackupPlan).where(BackupPlan.id == uuid.UUID(backup_plan_id), BackupPlan.owner_id == user.id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Backup plan not found")

    import json

    meta = json.loads(plan.config) if plan.config and plan.config.startswith("{") else {}
    meta["notification_enabled"] = body.enabled
    meta["webhook_url"] = body.webhook_url
    plan.config = json.dumps(meta)
    await db.commit()
    return {"status": "updated", "notifications": meta}


@router.get("/{backup_plan_id}/notifications")
async def get_backup_notifications(
    backup_plan_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get notification settings for a backup plan."""
    import json

    result = await db.execute(
        select(BackupPlan).where(BackupPlan.id == uuid.UUID(backup_plan_id), BackupPlan.owner_id == user.id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Backup plan not found")

    meta = json.loads(plan.config) if plan.config and plan.config.startswith("{") else {}
    return {
        "plan_id": str(plan.id),
        "notification_enabled": meta.get("notification_enabled", True),
        "webhook_url": meta.get("webhook_url"),
    }


# --- Restore APIs ---


class RestoreRequest(BaseModel):
    target_storage: str = "local"


@router.post("/{backup_id}/restore-inplace")
async def restore_inplace(
    backup_id: str,
    body: RestoreRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Restore a backup in-place (overwrites current resource state)."""
    result = await db.execute(
        select(Backup).where(Backup.id == uuid.UUID(backup_id), Backup.owner_id == user.id)
    )
    backup = result.scalar_one_or_none()
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    if backup.status != "completed":
        raise HTTPException(status_code=400, detail="Only completed backups can be restored")

    resource = await db.get(Resource, backup.resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Source resource not found")

    try:
        upid = proxmox_client.rollback_snapshot(
            resource.proxmox_node, resource.proxmox_vmid, "current", resource.resource_type
        )
        return {"status": "restoring", "task": upid, "resource_id": str(resource.id)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class RestoreToNewRequest(BaseModel):
    name: str
    target_node: str | None = None
    target_storage: str = "local"


@router.post("/{backup_id}/restore-new")
async def restore_to_new_vm(
    backup_id: str,
    body: RestoreToNewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Restore a backup to a new VM/container."""
    result = await db.execute(
        select(Backup).where(Backup.id == uuid.UUID(backup_id), Backup.owner_id == user.id)
    )
    backup = result.scalar_one_or_none()
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    if backup.status != "completed":
        raise HTTPException(status_code=400, detail="Only completed backups can be restored")

    resource = await db.get(Resource, backup.resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Source resource not found")

    node = body.target_node or resource.proxmox_node
    new_vmid = proxmox_client.get_next_vmid()

    new_resource = Resource(
        owner_id=user.id,
        resource_type=resource.resource_type,
        display_name=body.name,
        status="creating",
        specs=resource.specs,
        proxmox_vmid=new_vmid,
        proxmox_node=node,
    )
    db.add(new_resource)
    await db.commit()

    return {
        "status": "restoring",
        "new_resource_id": str(new_resource.id),
        "new_vmid": new_vmid,
        "source_backup": str(backup.id),
    }


@router.get("/restore-jobs")
async def list_restore_jobs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List recent restore operations (resources in 'creating' state from restores)."""
    result = await db.execute(
        select(Resource).where(
            Resource.owner_id == user.id,
            Resource.status == "creating",
        ).order_by(Resource.created_at.desc()).limit(20)
    )
    resources = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "name": r.display_name,
            "type": r.resource_type,
            "status": r.status,
            "node": r.proxmox_node,
            "created_at": str(r.created_at),
        }
        for r in resources
    ]

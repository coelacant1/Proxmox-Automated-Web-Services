"""Backup and snapshot management endpoints."""

import json as _json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import Backup, BackupPlan, Resource, SystemSetting, User, UserQuota
from app.services.audit_service import log_action
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/backups", tags=["backups"])
logger = logging.getLogger(__name__)


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
    result = await db.execute(select(Backup).where(Backup.id == uuid.UUID(backup_id), Backup.owner_id == user.id))
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
    result = await db.execute(select(Backup).where(Backup.id == uuid.UUID(backup_id), Backup.owner_id == user.id))
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
    result = await db.execute(select(Backup).where(Backup.id == uuid.UUID(backup_id), Backup.owner_id == user.id))
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
    result = await db.execute(select(Backup).where(Backup.id == uuid.UUID(backup_id), Backup.owner_id == user.id))
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
        select(Resource)
        .where(
            Resource.owner_id == user.id,
            Resource.status == "creating",
        )
        .order_by(Resource.created_at.desc())
        .limit(20)
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


# --- Global Proxmox Backups (all user resources) ---


def _get_any_node() -> str:
    """Get any available cluster node name for storage queries."""
    try:
        nodes = proxmox_client.get_nodes()
        if nodes:
            return nodes[0].get("node", "pve")
    except Exception:
        pass
    return "pve"


def _resolve_node(storage_entry: dict, fallback_node: str | None = None) -> str:
    """Resolve the node to use for a storage content query."""
    return storage_entry.get("node") or fallback_node or _get_any_node()


@router.get("/proxmox/all")
async def list_all_proxmox_backups(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List ALL Proxmox backup files across all user's resources."""
    # Get user's resources
    result = await db.execute(
        select(Resource).where(
            Resource.owner_id == user.id,
            Resource.resource_type.in_(["vm", "lxc"]),
            Resource.status != "destroyed",
        )
    )
    resources = result.scalars().all()
    resource_map = {}
    vmid_to_resource = {}
    for r in resources:
        resource_map[str(r.id)] = r
        if r.proxmox_vmid:
            vmid_to_resource[str(r.proxmox_vmid)] = r

    fallback_node = resources[0].proxmox_node if resources else None
    user_tag = f"[paws:{user.id}]"
    backups: list[dict] = []

    try:
        storages = proxmox_client.get_storage_list()
        for s in storages:
            if "backup" not in s.get("content", ""):
                continue
            try:
                node = _resolve_node(s, fallback_node)
                contents = proxmox_client.get_storage_content(node, s["storage"])
                is_pbs = s.get("type") == "pbs"
                for item in contents:
                    if item.get("content") != "backup":
                        continue
                    notes = item.get("notes", "") or ""
                    if user_tag not in notes:
                        continue
                    volid = item.get("volid", "")
                    # Match to resource by VMID
                    matched_resource = None
                    for vmid_str, r in vmid_to_resource.items():
                        if vmid_str in volid:
                            matched_resource = r
                            break

                    entry = {
                        "volid": volid,
                        "size": item.get("size", 0),
                        "ctime": item.get("ctime", 0),
                        "format": item.get("format", "pbs" if is_pbs else ""),
                        "storage": s["storage"],
                        "notes": notes,
                        "pbs": is_pbs,
                        "resource_id": str(matched_resource.id) if matched_resource else None,
                        "resource_name": matched_resource.display_name if matched_resource else None,
                        "resource_type": matched_resource.resource_type if matched_resource else None,
                        "vmid": matched_resource.proxmox_vmid if matched_resource else None,
                        "node": matched_resource.proxmox_node if matched_resource else (s.get("node") or None),
                    }
                    if is_pbs:
                        entry["backup_type"] = "ct" if "/ct/" in volid else "vm"
                        entry["backup_time"] = item.get("ctime", 0)
                    backups.append(entry)
            except Exception:
                pass
    except Exception:
        pass

    backups.sort(key=lambda b: b.get("ctime", 0), reverse=True)
    return {"backups": backups, "total": len(backups)}


@router.get("/quota-summary")
async def backup_quota_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get backup quota usage for the current user."""
    # Quota limits
    q_result = await db.execute(select(UserQuota).where(UserQuota.user_id == user.id))
    quota = q_result.scalar_one_or_none()
    max_snapshots = quota.max_snapshots if quota else 10
    max_backups = quota.max_backups if quota else 20
    max_backup_size_gb = quota.max_backup_size_gb if quota else 100

    # DB backup records count
    count_result = await db.execute(
        select(func.count(Backup.id)).where(
            Backup.owner_id == user.id,
            Backup.status.in_(["pending", "running", "completed"]),
        )
    )
    db_backup_count = count_result.scalar() or 0

    # Snapshot count from Proxmox (live per-resource)
    res_result = await db.execute(
        select(Resource).where(
            Resource.owner_id == user.id,
            Resource.resource_type.in_(["vm", "lxc"]),
            Resource.status != "destroyed",
        )
    )
    all_resources = res_result.scalars().all()
    snapshot_count = 0
    for r in all_resources:
        if not r.proxmox_vmid or not r.proxmox_node:
            continue
        try:
            vmtype = "lxc" if r.resource_type == "lxc" else "qemu"
            snaps = proxmox_client.list_snapshots(r.proxmox_node, r.proxmox_vmid, vmtype)
            snapshot_count += len([s for s in snaps if s.get("name") != "current"])
        except Exception:
            pass

    # Proxmox backup files total size
    fallback_node = all_resources[0].proxmox_node if all_resources else None
    user_tag = f"[paws:{user.id}]"
    total_backup_size = 0
    proxmox_backup_count = 0
    try:
        storages = proxmox_client.get_storage_list()
        for s in storages:
            if "backup" not in s.get("content", ""):
                continue
            try:
                node = _resolve_node(s, fallback_node)
                contents = proxmox_client.get_storage_content(node, s["storage"])
                for item in contents:
                    if item.get("content") != "backup":
                        continue
                    if user_tag not in (item.get("notes", "") or ""):
                        continue
                    proxmox_backup_count += 1
                    total_backup_size += item.get("size", 0)
            except Exception:
                pass
    except Exception:
        pass

    return {
        "max_snapshots": max_snapshots,
        "max_backups": max_backups,
        "max_backup_size_gb": max_backup_size_gb,
        "snapshot_count": snapshot_count,
        "db_backup_count": db_backup_count,
        "proxmox_backup_count": proxmox_backup_count,
        "total_backup_size": total_backup_size,
        "total_count": snapshot_count + proxmox_backup_count,
    }


@router.post("/proxmox/{resource_id}/download")
async def download_proxmox_backup(
    resource_id: str,
    volid: str = Query(...),
    storage: str = Query(...),
    filepath: str = Query(default="/"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Download a file from a Proxmox backup."""
    resource = await _get_resource(db, user.id, resource_id)

    try:
        data = proxmox_client.download_backup_file(
            resource.proxmox_node,
            storage,
            volid,
            filepath,
        )
        if isinstance(data, dict):
            content = data.get("errors", b"")
            if isinstance(content, str):
                content = content.encode()
        elif isinstance(data, bytes):
            content = data
        else:
            content = str(data).encode()
        filename = filepath.rsplit("/", 1)[-1] if "/" in filepath else filepath
        if not filename or filename == "/":
            filename = f"backup-{resource_id[:8]}.tar"
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/proxmox/{resource_id}/browse")
async def browse_proxmox_backup(
    resource_id: str,
    volid: str = Query(...),
    storage: str = Query(...),
    filepath: str = Query(default="/"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Browse files inside a Proxmox backup."""
    resource = await _get_resource(db, user.id, resource_id)

    try:
        files = proxmox_client.list_backup_files(
            resource.proxmox_node,
            storage,
            volid,
            filepath,
        )
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Admin Pruning & Management ---


class PrunePolicy(BaseModel):
    keep_last: int = 3
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 6


@router.get("/admin/pruning-policy")
async def get_pruning_policy(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Get admin backup pruning policy."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == "backup_pruning_policy"))
    setting = result.scalar_one_or_none()
    if setting:
        return _json.loads(setting.value)
    return {"keep_last": 3, "keep_daily": 7, "keep_weekly": 4, "keep_monthly": 6}


@router.put("/admin/pruning-policy")
async def set_pruning_policy(
    body: PrunePolicy,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Set admin backup pruning policy."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == "backup_pruning_policy"))
    setting = result.scalar_one_or_none()
    value = _json.dumps(body.model_dump())
    if setting:
        setting.value = value
    else:
        db.add(SystemSetting(key="backup_pruning_policy", value=value))
    await db.commit()
    await log_action(db, admin.id, "backup_pruning_policy_update", "system", None, body.model_dump())
    return {"status": "updated", **body.model_dump()}


@router.post("/admin/prune")
async def admin_prune_backups(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Run pruning on expired DB backup records."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(Backup).where(
            Backup.expires_at.isnot(None),
            Backup.expires_at < now,
            Backup.status == "completed",
        )
    )
    expired = result.scalars().all()
    pruned = 0
    for b in expired:
        try:
            if b.proxmox_volid and b.proxmox_storage:
                resource = await db.get(Resource, b.resource_id)
                if resource and resource.proxmox_node:
                    proxmox_client.delete_storage_content(resource.proxmox_node, b.proxmox_storage, b.proxmox_volid)
            await db.delete(b)
            pruned += 1
        except Exception:
            logger.exception("Failed to prune backup %s", b.id)
    await db.commit()
    await log_action(db, admin.id, "backup_prune", "system", None, {"pruned": pruned})
    return {"pruned": pruned, "total_expired": len(expired)}


@router.get("/admin/all")
async def admin_list_all_backups(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: list ALL Proxmox backup files across all users."""
    backups: list[dict] = []

    # Build resource lookup
    result = await db.execute(
        select(Resource).where(
            Resource.resource_type.in_(["vm", "lxc"]),
            Resource.status != "destroyed",
        )
    )
    vmid_map: dict[str, Resource] = {}
    for r in result.scalars().all():
        if r.proxmox_vmid:
            vmid_map[str(r.proxmox_vmid)] = r

    # Owner lookup
    user_result = await db.execute(select(User))
    user_map = {str(u.id): u.username for u in user_result.scalars().all()}

    try:
        storages = proxmox_client.get_storage_list()
        for s in storages:
            if "backup" not in s.get("content", ""):
                continue
            try:
                node = s.get("node", "pve")
                contents = proxmox_client.get_storage_content(node, s["storage"])
                is_pbs = s.get("type") == "pbs"
                for item in contents:
                    if item.get("content") != "backup":
                        continue
                    volid = item.get("volid", "")
                    notes = item.get("notes", "") or ""
                    # Extract owner from paws tag
                    owner_id = None
                    owner_name = None
                    if "[paws:" in notes:
                        try:
                            tag = notes.split("[paws:")[1].split("]")[0]
                            owner_id = tag
                            owner_name = user_map.get(tag, tag[:8])
                        except Exception:
                            pass

                    # Match resource
                    matched_resource = None
                    for vmid_str, r in vmid_map.items():
                        if vmid_str in volid:
                            matched_resource = r
                            break

                    backups.append(
                        {
                            "volid": volid,
                            "size": item.get("size", 0),
                            "ctime": item.get("ctime", 0),
                            "format": item.get("format", "pbs" if is_pbs else ""),
                            "storage": s["storage"],
                            "notes": notes,
                            "pbs": is_pbs,
                            "owner_id": owner_id,
                            "owner_name": owner_name,
                            "resource_id": str(matched_resource.id) if matched_resource else None,
                            "resource_name": matched_resource.display_name if matched_resource else None,
                            "node": s.get("node") or (matched_resource.proxmox_node if matched_resource else None),
                        }
                    )
            except Exception:
                pass
    except Exception:
        pass

    backups.sort(key=lambda b: b.get("ctime", 0), reverse=True)
    return {"backups": backups, "total": len(backups)}


@router.delete("/admin/backup")
async def admin_delete_backup(
    volid: str = Query(...),
    storage: str = Query(...),
    node: str = Query(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin: delete a specific Proxmox backup file."""
    try:
        proxmox_client.delete_storage_content(node, storage, volid)
        await log_action(db, admin.id, "admin_backup_delete", "backup", None, {"volid": volid, "storage": storage})
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

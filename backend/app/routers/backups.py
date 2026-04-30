"""Backup and snapshot management endpoints."""

import asyncio
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
from app.services.cache import cache_delete, cached_call
from app.services.proxmox_client import get_pve

router = APIRouter(prefix="/api/backups", tags=["backups"])
logger = logging.getLogger(__name__)


def _snapshots_cache_key(resource: Resource, vmtype: str) -> str:
    return f"pve:{resource.cluster_id or 'default'}:snapshots:{resource.proxmox_node}:{resource.proxmox_vmid}:{vmtype}"


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

    cache_key = _snapshots_cache_key(resource, vmtype)

    async def _fetch():
        try:
            snaps = await asyncio.to_thread(
                get_pve(resource.cluster_id).list_snapshots,
                resource.proxmox_node,
                resource.proxmox_vmid,
                vmtype,
            )
            return [s for s in snaps if s.get("name") != "current"]
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    return await cached_call(cache_key, 15, _fetch)


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
        pve = get_pve(resource.cluster_id)
        upid = await asyncio.to_thread(
            pve.create_snapshot, resource.proxmox_node, resource.proxmox_vmid, body.name, vmtype, **kwargs
        )
        await cache_delete(_snapshots_cache_key(resource, vmtype))
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
        pve = get_pve(resource.cluster_id)
        upid = await asyncio.to_thread(
            pve.rollback_snapshot, resource.proxmox_node, resource.proxmox_vmid, body.name, vmtype
        )
        await cache_delete(_snapshots_cache_key(resource, vmtype))
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
        pve = get_pve(resource.cluster_id)
        upid = await asyncio.to_thread(
            pve.delete_snapshot, resource.proxmox_node, resource.proxmox_vmid, snapshot_name, vmtype
        )
        await cache_delete(_snapshots_cache_key(resource, vmtype))
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
    cluster_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    query = select(Backup).where(Backup.owner_id == user.id).order_by(Backup.created_at.desc())
    if resource_id:
        query = query.where(Backup.resource_id == uuid.UUID(resource_id))
    if cluster_id:
        query = query.where(Backup.cluster_id == cluster_id)
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
        cluster_id=resource.cluster_id,
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
        cluster_id=resource.cluster_id,
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
        pve = get_pve(resource.cluster_id)
        snapshots = pve.list_snapshots(resource.proxmox_node, resource.proxmox_vmid, resource.resource_type)
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
        upid = get_pve(resource.cluster_id).rollback_snapshot(
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
    new_vmid = get_pve(resource.cluster_id).get_next_vmid()

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


def _get_any_node(cluster_id: str | None = None) -> str:
    """Get any available cluster node name for storage queries."""
    try:
        nodes = get_pve(cluster_id).get_nodes()
        if nodes:
            return nodes[0].get("node", "pve")
    except Exception:
        pass
    return "pve"


def _resolve_node(
    storage_entry: dict,
    fallback_node: str | None = None,
    cluster_id: str | None = None,
) -> str:
    """Resolve the node to use for a storage content query."""
    return storage_entry.get("node") or fallback_node or _get_any_node(cluster_id)


@router.get("/proxmox/all")
async def list_all_proxmox_backups(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List ALL Proxmox backup files across all user's resources.

    Cached per-user for 30 s in Redis. Per-cluster ``get_storage_list`` and
    per-storage ``get_storage_content`` calls run concurrently via
    ``asyncio.gather`` + ``to_thread`` so they no longer serialize the event
    loop.
    """
    # Get user's resources
    result = await db.execute(
        select(Resource).where(
            Resource.owner_id == user.id,
            Resource.resource_type.in_(["vm", "lxc"]),
            Resource.status != "destroyed",
        )
    )
    resources = list(result.scalars().all())
    vmid_to_resource = {str(r.proxmox_vmid): r for r in resources if r.proxmox_vmid}

    fallback_node = resources[0].proxmox_node if resources else None
    user_tag = f"[paws:{user.id}]"
    cluster_ids = {r.cluster_id for r in resources}

    cache_key = f"backup_list_proxmox_all:{user.id}"

    async def _scan() -> list[dict]:
        async def _scan_cluster(cid: str | None) -> list[dict]:
            try:
                pve = get_pve(cid)
                storages = await asyncio.to_thread(pve.get_storage_list)
            except Exception:
                return []
            backup_storages = [s for s in storages if "backup" in (s.get("content") or "")]

            async def _scan_storage(s: dict) -> list[dict]:
                try:
                    node = _resolve_node(s, fallback_node, cid)
                    contents = await asyncio.to_thread(pve.get_storage_content, node, s["storage"])
                except Exception:
                    return []
                is_pbs = s.get("type") == "pbs"
                out: list[dict] = []
                for item in contents:
                    if item.get("content") != "backup":
                        continue
                    notes = item.get("notes", "") or ""
                    if user_tag not in notes:
                        continue
                    volid = item.get("volid", "")
                    matched = next((r for vmid, r in vmid_to_resource.items() if vmid in volid), None)
                    entry = {
                        "volid": volid,
                        "size": item.get("size", 0),
                        "ctime": item.get("ctime", 0),
                        "format": item.get("format", "pbs" if is_pbs else ""),
                        "storage": s["storage"],
                        "notes": notes,
                        "pbs": is_pbs,
                        "resource_id": str(matched.id) if matched else None,
                        "resource_name": matched.display_name if matched else None,
                        "resource_type": matched.resource_type if matched else None,
                        "vmid": matched.proxmox_vmid if matched else None,
                        "node": matched.proxmox_node if matched else (s.get("node") or None),
                    }
                    if is_pbs:
                        entry["backup_type"] = "ct" if "/ct/" in volid else "vm"
                        entry["backup_time"] = item.get("ctime", 0)
                    out.append(entry)
                return out

            results = await asyncio.gather(*[_scan_storage(s) for s in backup_storages])
            return [item for sub in results for item in sub]

        cluster_results = await asyncio.gather(*[_scan_cluster(cid) for cid in cluster_ids])
        all_backups = [b for sub in cluster_results for b in sub]
        all_backups.sort(key=lambda b: b.get("ctime", 0), reverse=True)
        return all_backups

    backups = await cached_call(cache_key, 30, _scan)
    return {"backups": backups, "total": len(backups)}


@router.get("/quota-summary")
async def backup_quota_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get backup quota usage for the current user.

    Cached per-user for 30 s in Redis because the underlying Proxmox calls
    (per-VM ``list_snapshots`` + per-storage ``get_storage_content``) are
    expensive and the data is only used for an at-a-glance UI counter.
    """
    # Quota limits (always read fresh from DB)
    q_result = await db.execute(select(UserQuota).where(UserQuota.user_id == user.id))
    quota = q_result.scalar_one_or_none()
    max_snapshots = quota.max_snapshots if quota else 10
    max_backups = quota.max_backups if quota else 20
    max_backup_size_gb = quota.max_backup_size_gb if quota else 100

    # DB backup records count (cheap)
    count_result = await db.execute(
        select(func.count(Backup.id)).where(
            Backup.owner_id == user.id,
            Backup.status.in_(["pending", "running", "completed"]),
        )
    )
    db_backup_count = count_result.scalar() or 0

    # User's VM/LXC resources (needed to look up live counts from PVE)
    res_result = await db.execute(
        select(Resource).where(
            Resource.owner_id == user.id,
            Resource.resource_type.in_(["vm", "lxc"]),
            Resource.status != "destroyed",
        )
    )
    all_resources = list(res_result.scalars().all())

    # Heavy section: snapshot count + proxmox backup totals.
    # Per-VM list_snapshots and per-storage get_storage_content are sync HTTP
    # calls; running them serially in an async handler blocks the event loop
    # and serializes every other request. Parallelize with to_thread + gather
    # and cache the aggregate per-user.
    cache_key = f"backup_quota_summary:{user.id}"

    async def _compute_pve_counts() -> dict:
        # --- Snapshots: one call per resource, run in parallel ---
        async def _count_snaps(r: Resource) -> int:
            if not r.proxmox_vmid or not r.proxmox_node:
                return 0
            try:
                vmtype = "lxc" if r.resource_type == "lxc" else "qemu"
                snaps = await asyncio.to_thread(
                    get_pve(r.cluster_id).list_snapshots, r.proxmox_node, r.proxmox_vmid, vmtype
                )
                return len([s for s in snaps if s.get("name") != "current"])
            except Exception:
                return 0

        snap_counts = await asyncio.gather(*[_count_snaps(r) for r in all_resources])
        total_snaps = sum(snap_counts)

        # --- Proxmox backup files: one call per (cluster, storage), parallelized ---
        fallback_node = all_resources[0].proxmox_node if all_resources else None
        user_tag = f"[paws:{user.id}]"
        cluster_ids = {r.cluster_id for r in all_resources}

        async def _scan_cluster(cid: str | None) -> tuple[int, int]:
            try:
                pve = get_pve(cid)
                storages = await asyncio.to_thread(pve.get_storage_list)
            except Exception:
                return 0, 0
            backup_storages = [s for s in storages if "backup" in (s.get("content") or "")]

            async def _scan_storage(s: dict) -> tuple[int, int]:
                try:
                    node = _resolve_node(s, fallback_node, cid)
                    contents = await asyncio.to_thread(pve.get_storage_content, node, s["storage"])
                except Exception:
                    return 0, 0
                cnt = 0
                size = 0
                for item in contents:
                    if item.get("content") != "backup":
                        continue
                    if user_tag not in (item.get("notes", "") or ""):
                        continue
                    cnt += 1
                    size += item.get("size", 0)
                return cnt, size

            results = await asyncio.gather(*[_scan_storage(s) for s in backup_storages])
            return sum(c for c, _ in results), sum(sz for _, sz in results)

        cluster_results = await asyncio.gather(*[_scan_cluster(cid) for cid in cluster_ids])
        total_backup_count = sum(c for c, _ in cluster_results)
        total_backup_size = sum(sz for _, sz in cluster_results)

        return {
            "snapshot_count": total_snaps,
            "proxmox_backup_count": total_backup_count,
            "total_backup_size": total_backup_size,
        }

    pve_counts = await cached_call(cache_key, 30, _compute_pve_counts)

    return {
        "max_snapshots": max_snapshots,
        "max_backups": max_backups,
        "max_backup_size_gb": max_backup_size_gb,
        "snapshot_count": pve_counts["snapshot_count"],
        "db_backup_count": db_backup_count,
        "proxmox_backup_count": pve_counts["proxmox_backup_count"],
        "total_backup_size": pve_counts["total_backup_size"],
        "total_count": pve_counts["snapshot_count"] + pve_counts["proxmox_backup_count"],
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
        data = get_pve(resource.cluster_id).download_backup_file(
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
        files = get_pve(resource.cluster_id).list_backup_files(
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
                    pve = get_pve(resource.cluster_id)
                    pve.delete_storage_content(resource.proxmox_node, b.proxmox_storage, b.proxmox_volid)
            await db.delete(b)
            pruned += 1
        except Exception:
            logger.exception("Failed to prune backup %s", b.id)
    await db.commit()
    await log_action(db, admin.id, "backup_prune", "system", None, {"pruned": pruned})
    return {"pruned": pruned, "total_expired": len(expired)}


@router.get("/admin/all")
async def admin_list_all_backups(
    cluster_id: str | None = Query(None, description="Target cluster"),
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
    all_resources = list(result.scalars().all())
    vmid_map: dict[str, Resource] = {}
    for r in all_resources:
        if r.proxmox_vmid:
            vmid_map[str(r.proxmox_vmid)] = r

    # Owner lookup
    user_result = await db.execute(select(User))
    user_map = {str(u.id): u.username for u in user_result.scalars().all()}

    # Determine which clusters to scan
    if cluster_id is not None:
        scan_cluster_ids = {cluster_id}
    else:
        scan_cluster_ids = {r.cluster_id for r in all_resources}
        scan_cluster_ids.add(None)  # include default cluster

    for cid in scan_cluster_ids:
        try:
            pve = get_pve(cid)
            storages = pve.get_storage_list()
            for s in storages:
                if "backup" not in s.get("content", ""):
                    continue
                try:
                    node = s.get("node", "pve")
                    contents = pve.get_storage_content(node, s["storage"])
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
    cluster_id: str | None = Query(None, description="Target cluster"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin: delete a specific Proxmox backup file."""
    try:
        get_pve(cluster_id).delete_storage_content(node, storage, volid)
        await log_action(db, admin.id, "admin_backup_delete", "backup", None, {"volid": volid, "storage": storage})
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

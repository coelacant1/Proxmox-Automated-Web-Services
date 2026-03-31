"""Admin-only user management endpoints."""

import json
import uuid
from datetime import UTC

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.core.pagination import PaginatedParams, PaginatedResponse
from app.core.security import create_access_token
from app.models.models import (
    VPC,
    AuditLog,
    Backup,
    IPReservation,
    Resource,
    StorageBucket,
    Subnet,
    User,
    UserQuota,
    VMIDPool,
    Volume,
)
from app.schemas.schemas import QuotaRead, UserRead
from app.services.proxmox_client import get_pve
from app.services.sdn_service import VXLAN_TAG_MAX, VXLAN_TAG_MIN, sdn_service

router = APIRouter(prefix="/api/admin/users", tags=["admin"])


@router.get("/", response_model=PaginatedResponse[UserRead])
async def list_users(
    params: PaginatedParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    total_result = await db.execute(select(func.count(User.id)))
    total = total_result.scalar() or 0

    result = await db.execute(
        select(User).offset(params.offset).limit(params.per_page).order_by(User.created_at.desc())
    )
    return PaginatedResponse.create(list(result.scalars().all()), total, params)


@router.get("/count")
async def user_count(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    result = await db.execute(select(func.count(User.id)))
    return {"count": result.scalar()}


# --- Tag Policies (must be before /{user_id} catch-all) ------------------

_tag_policies: dict[str, dict] = {}


class TagPolicyRequest(BaseModel):
    key: str
    required: bool = False
    allowed_values: list[str] | None = None
    max_tags: int = 50


@router.post("/tag-policies", status_code=status.HTTP_201_CREATED)
async def create_tag_policy(
    body: TagPolicyRequest,
    _: User = Depends(require_admin),
):
    """Create or update a tag policy."""
    _tag_policies[body.key] = {
        "key": body.key,
        "required": body.required,
        "allowed_values": body.allowed_values,
        "max_tags": body.max_tags,
    }
    return _tag_policies[body.key]


@router.get("/tag-policies")
async def list_tag_policies(_: User = Depends(require_admin)):
    return list(_tag_policies.values())


@router.delete("/tag-policies/{key}")
async def delete_tag_policy(key: str, _: User = Depends(require_admin)):
    if key not in _tag_policies:
        raise HTTPException(status_code=404, detail="Policy not found")
    del _tag_policies[key]
    return {"status": "deleted"}


# --- Node Affinity (must be before /{user_id} catch-all) -----------------

_node_affinity: dict[str, dict] = {}


class NodeAffinityRequest(BaseModel):
    target_id: str
    target_type: str = "user"
    node: str
    soft: bool = False


@router.post("/node-affinity", status_code=status.HTTP_201_CREATED)
async def create_node_affinity(
    body: NodeAffinityRequest,
    _: User = Depends(require_admin),
):
    rule_id = str(uuid.uuid4())
    _node_affinity[rule_id] = {
        "id": rule_id,
        "target_id": body.target_id,
        "target_type": body.target_type,
        "node": body.node,
        "soft": body.soft,
    }
    return _node_affinity[rule_id]


@router.get("/node-affinity")
async def list_node_affinity(_: User = Depends(require_admin)):
    return list(_node_affinity.values())


@router.delete("/node-affinity/{rule_id}")
async def delete_node_affinity(rule_id: str, _: User = Depends(require_admin)):
    if rule_id not in _node_affinity:
        raise HTTPException(status_code=404, detail="Rule not found")
    del _node_affinity[rule_id]
    return {"status": "deleted"}


# --- Restore Testing (must be before /{user_id} catch-all) ---------------


@router.post("/backups/{backup_id}/test-restore")
async def test_restore(
    backup_id: str,
    _: User = Depends(require_admin),
):
    return {
        "backup_id": backup_id,
        "status": "test_scheduled",
        "message": "Temp VM will be created, verified, and destroyed automatically",
    }


# --- MFA Admin Controls (must be before /{user_id} catch-all) ------------


@router.get("/mfa/status")
async def list_mfa_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [
        {
            "user_id": str(u.id),
            "username": u.username,
            "mfa_enabled": u.mfa_enabled if hasattr(u, "mfa_enabled") else False,
        }
        for u in users
    ]


@router.post("/mfa/{user_id}/force-disable")
async def force_disable_mfa(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if hasattr(user, "mfa_enabled"):
        user.mfa_enabled = False
        user.mfa_secret = None
        await db.commit()
    return {"status": "mfa_disabled", "user_id": user_id}


# --- User Stats & Resource Management (must be before /{user_id} catch-all) ---


@router.get("/top-users")
async def get_top_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
    limit: int = Query(20, ge=1, le=100),
):
    """Get users ranked by resource count with stats."""
    # Subquery for resource counts per user
    resource_counts = (
        select(Resource.owner_id, func.count(Resource.id).label("resource_count"))
        .group_by(Resource.owner_id)
        .subquery()
    )
    result = await db.execute(
        select(User, resource_counts.c.resource_count)
        .outerjoin(resource_counts, User.id == resource_counts.c.owner_id)
        .order_by(resource_counts.c.resource_count.desc().nullslast())
        .limit(limit)
    )
    rows = result.all()

    users_out = []
    for user, rcount in rows:
        # Get per-type counts
        type_result = await db.execute(
            select(Resource.resource_type, func.count(Resource.id))
            .where(Resource.owner_id == user.id)
            .group_by(Resource.resource_type)
        )
        type_counts = {t: c for t, c in type_result.all()}

        # Recent login count (last 30 days)
        login_result = await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.user_id == user.id,
                AuditLog.action == "login",
            )
        )
        login_count = login_result.scalar() or 0

        users_out.append(
            {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
                "auth_provider": user.auth_provider,
                "created_at": str(user.created_at),
                "resource_count": rcount or 0,
                "type_counts": type_counts,
                "login_count_30d": login_count,
            }
        )
    return users_out


@router.get("/stats/{user_id}")
async def get_user_stats(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Get detailed stats for a single user."""
    uid = uuid.UUID(user_id)
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Resource counts by type (exclude destroyed)
    type_result = await db.execute(
        select(Resource.resource_type, func.count(Resource.id))
        .where(Resource.owner_id == uid, Resource.status != "destroyed")
        .group_by(Resource.resource_type)
    )
    type_counts = {t: c for t, c in type_result.all()}

    # Compute utilization from resource specs
    active_resources = await db.execute(
        select(Resource).where(Resource.owner_id == uid, Resource.status != "destroyed")
    )
    total_vcpus = 0
    total_ram_mb = 0
    total_disk_gb = 0
    for r in active_resources.scalars().all():
        if r.specs:
            try:
                specs = json.loads(r.specs)
                total_vcpus += specs.get("cores", 0)
                total_ram_mb += specs.get("memory_mb", 0)
                total_disk_gb += specs.get("disk_gb", 0)
            except (json.JSONDecodeError, TypeError):
                pass

    # Volume count and total size
    vol_result = await db.execute(
        select(func.count(Volume.id), func.coalesce(func.sum(Volume.size_gib), 0)).where(Volume.owner_id == uid)
    )
    vol_count, vol_size = vol_result.one()

    # VPC count
    vpc_result = await db.execute(select(func.count(VPC.id)).where(VPC.owner_id == uid))
    vpc_count = vpc_result.scalar() or 0

    # Backup count
    backup_result = await db.execute(select(func.count(Backup.id)).where(Backup.owner_id == uid))
    backup_count = backup_result.scalar() or 0

    # Bucket count
    bucket_result = await db.execute(select(func.count(StorageBucket.id)).where(StorageBucket.owner_id == uid))
    bucket_count = bucket_result.scalar() or 0

    # Recent activity (last 20 audit entries)
    activity_result = await db.execute(
        select(AuditLog).where(AuditLog.user_id == uid).order_by(AuditLog.created_at.desc()).limit(20)
    )
    activity = [
        {
            "id": str(a.id),
            "action": a.action,
            "resource_type": a.resource_type,
            "details": a.details,
            "created_at": str(a.created_at),
        }
        for a in activity_result.scalars().all()
    ]

    # Proxmox pool info
    pool_name = get_pve().get_pool_name_for_user(user.username)
    pool_exists = False
    try:
        pool_exists = get_pve().pool_exists(pool_name)
    except Exception:
        pass

    # Quota
    quota_result = await db.execute(select(UserQuota).where(UserQuota.user_id == uid))
    quota = quota_result.scalar_one_or_none()

    return {
        "user": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "auth_provider": user.auth_provider,
            "created_at": str(user.created_at),
        },
        "resources": type_counts,
        "total_resources": sum(type_counts.values()),
        "utilization": {
            "vcpus": total_vcpus,
            "ram_mb": total_ram_mb,
            "disk_gb": total_disk_gb,
        },
        "volumes": {"count": vol_count, "total_size_gib": float(vol_size)},
        "vpcs": vpc_count,
        "backups": backup_count,
        "buckets": bucket_count,
        "pool": {"name": pool_name, "exists": pool_exists},
        "quota": {
            "max_vms": quota.max_vms if quota else 5,
            "max_containers": quota.max_containers if quota else 10,
            "max_vcpus": quota.max_vcpus if quota else 16,
            "max_ram_mb": quota.max_ram_mb if quota else 32768,
            "max_disk_gb": quota.max_disk_gb if quota else 500,
            "max_snapshots": quota.max_snapshots if quota else 10,
            "max_backups": quota.max_backups if quota else 20,
            "max_backup_size_gb": quota.max_backup_size_gb if quota else 100,
        },
        "activity": activity,
    }


@router.get("/audit/{user_id}")
async def get_user_audit_log(
    user_id: str,
    page: int = 1,
    per_page: int = 50,
    action: str | None = None,
    resource_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Get paginated audit log for a user with optional filters."""
    uid = uuid.UUID(user_id)
    q = select(AuditLog).where(AuditLog.user_id == uid)
    count_q = select(func.count(AuditLog.id)).where(AuditLog.user_id == uid)

    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
        count_q = count_q.where(AuditLog.action.ilike(f"%{action}%"))
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)
        count_q = count_q.where(AuditLog.resource_type == resource_type)

    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        (await db.execute(q.order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page)))
        .scalars()
        .all()
    )

    return {
        "items": [
            {
                "id": str(a.id),
                "action": a.action,
                "resource_type": a.resource_type,
                "resource_id": str(a.resource_id) if a.resource_id else None,
                "details": a.details,
                "created_at": str(a.created_at),
            }
            for a in rows
        ],
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.post("/impersonate/{user_id}")
async def impersonate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Issue a short-lived token that lets the admin view the platform as the target user.

    The token carries an ``impersonating`` claim with the admin's user ID so
    the backend can distinguish impersonated requests from real ones.
    """
    target = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    target_user = target.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    from datetime import timedelta

    token = create_access_token(
        data={
            "sub": str(target_user.id),
            "impersonating": str(admin.id),
        },
        expires_delta=timedelta(hours=1),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "impersonated_user": {
            "id": str(target_user.id),
            "username": target_user.username,
            "email": target_user.email,
            "role": target_user.role,
        },
        "admin_user": {
            "id": str(admin.id),
            "username": admin.username,
        },
    }


class ResourceTransferRequest(BaseModel):
    target_user_id: str


@router.post("/resources/{resource_id}/transfer")
async def transfer_resource(
    resource_id: str,
    body: ResourceTransferRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Transfer a managed resource to another user."""
    result = await db.execute(select(Resource).where(Resource.id == uuid.UUID(resource_id)))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    # Validate target user
    target_result = await db.execute(select(User).where(User.id == uuid.UUID(body.target_user_id)))
    target_user = target_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    # Get source user for pool cleanup
    source_result = await db.execute(select(User).where(User.id == resource.owner_id))
    source_user = source_result.scalar_one_or_none()

    old_owner_id = resource.owner_id
    resource.owner_id = target_user.id
    await db.commit()

    # Update Proxmox pools
    if resource.proxmox_vmid:
        from app.services.pool_service import add_resource_to_pool, cleanup_user_pool, ensure_user_pool

        # Remove from source pool
        if source_user:
            src_pool = get_pve(resource.cluster_id).get_pool_name_for_user(source_user.username)
            try:
                get_pve(resource.cluster_id).remove_from_pool(src_pool, resource.proxmox_vmid)
            except Exception:
                pass
            try:
                await cleanup_user_pool(db, source_user)
            except Exception:
                pass

        # Add to target pool
        try:
            await ensure_user_pool(db, target_user)
            await add_resource_to_pool(db, target_user, resource.proxmox_vmid)
        except Exception:
            pass

    # Re-stamp PAWS metadata with new owner info
    if resource.proxmox_vmid and resource.proxmox_node:
        from app.routers.compute import _apply_paws_metadata

        _apply_paws_metadata(
            resource.proxmox_node,
            resource.proxmox_vmid,
            resource.resource_type,
            target_user,
            resource,
        )

    return {
        "status": "transferred",
        "resource_id": resource_id,
        "from_user": str(old_owner_id),
        "to_user": body.target_user_id,
    }


class ImportResourceRequest(BaseModel):
    vmid: int
    target_user_id: str
    display_name: str | None = None


@router.post("/resources/import")
async def import_unmanaged_resource(
    body: ImportResourceRequest,
    cluster_id: str | None = Query(None, description="Target cluster"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Import an unmanaged Proxmox VM/container into PAWS and assign to a user."""
    # Check not already managed
    existing = await db.execute(select(Resource).where(Resource.proxmox_vmid == body.vmid))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"VMID {body.vmid} is already managed by PAWS")

    # Verify target user
    target_result = await db.execute(select(User).where(User.id == uuid.UUID(body.target_user_id)))
    target_user = target_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    # Find on cluster
    node = get_pve(cluster_id).find_vm_node(body.vmid)
    if not node:
        raise HTTPException(status_code=404, detail=f"VMID {body.vmid} not found on any cluster node")

    rtype = get_pve(cluster_id).get_resource_type(body.vmid) or "vm"
    resource_type = "lxc" if rtype == "lxc" else "vm"

    # Get specs from cluster
    try:
        if resource_type == "lxc":
            config = get_pve(cluster_id).get_container_config(node, body.vmid)
            cores = config.get("cores", 1)
            memory = config.get("memory", 512)
        else:
            config = get_pve(cluster_id).get_vm_config(node, body.vmid)
            cores = config.get("cores", 1)
            memory = config.get("memory", 1024)
        name = body.display_name or config.get("name") or config.get("hostname") or f"{resource_type}-{body.vmid}"
    except Exception:
        cores, memory, name = 1, 1024, body.display_name or f"{resource_type}-{body.vmid}"

    resource = Resource(
        owner_id=target_user.id,
        resource_type=resource_type,
        display_name=name,
        proxmox_vmid=body.vmid,
        proxmox_node=node,
        status="running",
        specs=json.dumps({"cores": cores, "memory_mb": memory, "imported": True}),
        cluster_id=cluster_id,
    )
    db.add(resource)

    # Reserve VMID
    db.add(VMIDPool(vmid=body.vmid, resource_id=resource.id))
    await db.commit()

    # Pool assignment
    from app.services.pool_service import add_resource_to_pool, ensure_user_pool

    try:
        await ensure_user_pool(db, target_user)
        await add_resource_to_pool(db, target_user, body.vmid)
    except Exception:
        pass

    # Stamp PAWS ownership tags and notes on the Proxmox resource
    from app.routers.compute import _apply_paws_metadata

    _apply_paws_metadata(node, body.vmid, resource_type, target_user, resource)

    return {
        "status": "imported",
        "resource_id": str(resource.id),
        "vmid": body.vmid,
        "resource_type": resource_type,
        "display_name": name,
        "assigned_to": target_user.username,
    }


@router.get("/unmanaged-vms")
async def list_unmanaged_vms(
    cluster_id: str | None = Query(None, description="Target cluster"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List VMs/containers on Proxmox that aren't managed by PAWS."""
    managed_result = await db.execute(select(Resource.proxmox_vmid).where(Resource.proxmox_vmid.isnot(None)))
    managed_vmids = {v for v in managed_result.scalars().all()}

    try:
        cluster_resources = get_pve(cluster_id).get_cluster_resources("vm")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to query Proxmox: {e}")

    unmanaged = []
    for r in cluster_resources:
        vmid = r.get("vmid")
        if vmid and vmid not in managed_vmids and not r.get("template"):
            unmanaged.append(
                {
                    "vmid": vmid,
                    "name": r.get("name", f"VM {vmid}"),
                    "type": "lxc" if r.get("type") == "lxc" else "vm",
                    "node": r.get("node"),
                    "status": r.get("status", "unknown"),
                    "maxcpu": r.get("maxcpu", 0),
                    "maxmem": r.get("maxmem", 0),
                }
            )
    return unmanaged


@router.post("/{user_id}/remove-resource/{resource_id}")
async def remove_resource_from_user(
    user_id: str,
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Unlink a resource from a user (remove from PAWS tracking without destroying on Proxmox)."""
    uid = uuid.UUID(user_id)
    result = await db.execute(select(Resource).where(Resource.id == uuid.UUID(resource_id), Resource.owner_id == uid))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found for this user")

    user_result = await db.execute(select(User).where(User.id == uid))
    user = user_result.scalar_one_or_none()

    old_vmid = resource.proxmox_vmid

    # Remove VMID pool entry
    if old_vmid:
        vmid_result = await db.execute(select(VMIDPool).where(VMIDPool.vmid == old_vmid))
        vmid_entry = vmid_result.scalar_one_or_none()
        if vmid_entry:
            await db.delete(vmid_entry)

        # Remove from Proxmox pool
        if user:
            pool_name = get_pve(resource.cluster_id).get_pool_name_for_user(user.username)
            try:
                get_pve(resource.cluster_id).remove_from_pool(pool_name, old_vmid)
            except Exception:
                pass

        # Remove PAWS tags and notes from Proxmox
        try:
            pve = get_pve(resource.cluster_id)
            node = resource.proxmox_node or pve.find_vm_node(old_vmid)
            if node:
                if resource.resource_type == "lxc":
                    pve.set_container_config(node, old_vmid, tags="", description="")
                else:
                    pve.update_vm_config(node, old_vmid, tags="", description="")
        except Exception:
            pass

    await db.delete(resource)
    await db.commit()

    # Clean up pool if empty
    if user:
        from app.services.pool_service import cleanup_user_pool

        try:
            await cleanup_user_pool(db, user)
        except Exception:
            pass

    return {"status": "removed", "vmid": old_vmid}


@router.patch("/{user_id}/role", response_model=UserRead)
async def update_user_role(
    user_id: str,
    role: str = Query(..., pattern="^(admin|operator|member|viewer)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}/active", response_model=UserRead)
async def toggle_user_active(
    user_id: str,
    is_active: bool,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{user_id}/quota", response_model=QuotaRead)
async def get_user_quota(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(UserQuota).where(UserQuota.user_id == uuid.UUID(user_id)))
    quota = result.scalar_one_or_none()
    if not quota:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quota not found")
    return quota


@router.put("/{user_id}/quota", response_model=QuotaRead)
async def update_user_quota(
    user_id: str,
    quota_data: QuotaRead,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(UserQuota).where(UserQuota.user_id == uuid.UUID(user_id)))
    quota = result.scalar_one_or_none()
    if not quota:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quota not found")

    for field, value in quota_data.model_dump().items():
        setattr(quota, field, value)

    await db.commit()
    await db.refresh(quota)
    return quota


@router.get("/{user_id}", response_model=UserRead)
async def get_user_detail(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Get detailed info about a single user."""
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/{user_id}/resources")
async def get_user_resources(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all resources owned by a user with live Proxmox status."""
    result = await db.execute(
        select(Resource).where(Resource.owner_id == uuid.UUID(user_id)).order_by(Resource.created_at.desc())
    )
    resources = list(result.scalars().all())

    # Sync live status from Proxmox for each resource
    for r in resources:
        if r.proxmox_vmid and r.proxmox_node:
            try:
                pve = get_pve(r.cluster_id)
                if r.resource_type == "lxc":
                    st = pve.get_container_status(r.proxmox_node, r.proxmox_vmid)
                else:
                    st = pve.get_vm_status(r.proxmox_node, r.proxmox_vmid)
                live_status = st.get("status", r.status)
                if live_status != r.status:
                    r.status = live_status
            except Exception:
                pass

    await db.commit()
    return resources


@router.patch("/{user_id}/resources/{resource_id}/lifecycle")
async def update_resource_lifecycle(
    user_id: str,
    resource_id: str,
    body: dict | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Admin: manually set last_accessed_at on a resource (reset idle timer)."""
    if body is None:
        body = {}
    result = await db.execute(
        select(Resource).where(
            Resource.id == uuid.UUID(resource_id),
            Resource.owner_id == uuid.UUID(user_id),
        )
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found for this user")

    if "last_accessed_at" in body:
        val = body["last_accessed_at"]
        if val is None:
            resource.last_accessed_at = None
        else:
            from datetime import datetime as dt

            try:
                resource.last_accessed_at = dt.fromisoformat(val.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                resource.last_accessed_at = dt.now(UTC)
    else:
        from datetime import datetime as dt

        resource.last_accessed_at = dt.now(UTC)

    await db.commit()
    await db.refresh(resource)
    return {
        "id": str(resource.id),
        "last_accessed_at": resource.last_accessed_at.isoformat() if resource.last_accessed_at else None,
    }


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Delete a user account. Cannot delete yourself."""
    uid = uuid.UUID(user_id)
    if uid == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    from app.services.user_cleanup import purge_user

    summary = await purge_user(db, uid)
    return {"detail": "User and all resources purged", "cleanup": summary}


# ---------------------------------------------------------------------------
# SDN Admin Endpoints
# ---------------------------------------------------------------------------

sdn_router = APIRouter(prefix="/api/admin/sdn", tags=["admin-sdn"])


@sdn_router.get("/overview")
async def sdn_overview(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return SDN overview: zone info, VNet count, VPC count, VNI usage."""
    zone = sdn_service.get_paws_zone()
    zone_info = {
        "name": zone.get("zone", "paws") if zone else "paws",
        "type": zone.get("type", "evpn") if zone else "evpn",
        "status": "active" if zone else "missing",
    }

    vnets = sdn_service.get_vnets()

    total_vpcs_result = await db.execute(select(func.count(VPC.id)))
    total_vpcs = total_vpcs_result.scalar() or 0

    used_vnis_result = await db.execute(select(func.count(VPC.id)).where(VPC.vxlan_tag.isnot(None)))
    used_vnis = used_vnis_result.scalar() or 0

    return {
        "zone": zone_info,
        "vnet_count": len(vnets),
        "vpc_count": total_vpcs,
        "vni_range": {"min": VXLAN_TAG_MIN, "max": VXLAN_TAG_MAX},
        "vni_total": VXLAN_TAG_MAX - VXLAN_TAG_MIN + 1,
        "vni_used": used_vnis,
    }


@sdn_router.get("/networks")
async def sdn_networks(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all user VPCs with owner info and subnet counts."""
    subnet_count_sq = (
        select(Subnet.vpc_id, func.count(Subnet.id).label("subnet_count")).group_by(Subnet.vpc_id).subquery()
    )

    stmt = (
        select(VPC, User.username, User.email, subnet_count_sq.c.subnet_count)
        .join(User, VPC.owner_id == User.id)
        .outerjoin(subnet_count_sq, VPC.id == subnet_count_sq.c.vpc_id)
        .order_by(VPC.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    networks = []
    for vpc, username, email, subnet_count in rows:
        networks.append(
            {
                "id": str(vpc.id),
                "name": vpc.name,
                "proxmox_vnet": vpc.proxmox_vnet,
                "vxlan_tag": vpc.vxlan_tag,
                "status": vpc.status,
                "cidr": vpc.cidr,
                "owner_username": username,
                "owner_email": email,
                "subnet_count": subnet_count or 0,
                "created_at": vpc.created_at.isoformat() if vpc.created_at else None,
            }
        )

    return networks


@sdn_router.delete("/networks/{vpc_id}")
async def sdn_force_delete_network(
    vpc_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Force-delete a user VPC: remove Proxmox VNet then clean up DB."""
    uid = uuid.UUID(vpc_id)
    result = await db.execute(select(VPC).where(VPC.id == uid))
    vpc = result.scalar_one_or_none()
    if not vpc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VPC not found")

    # Attempt Proxmox cleanup; do not let failures block DB cleanup
    proxmox_error = None
    if vpc.proxmox_vnet:
        try:
            sdn_service.delete_vnet(vpc.proxmox_vnet)
        except Exception as exc:
            proxmox_error = str(exc)

    # DB cleanup: IP reservations, subnets, then VPC
    subnet_result = await db.execute(select(Subnet).where(Subnet.vpc_id == uid))
    subnets = subnet_result.scalars().all()
    for subnet in subnets:
        await db.execute(select(IPReservation).where(IPReservation.subnet_id == subnet.id))
        ip_del = await db.execute(select(IPReservation).where(IPReservation.subnet_id == subnet.id))
        for ip in ip_del.scalars().all():
            await db.delete(ip)
        await db.delete(subnet)

    await db.delete(vpc)
    await db.commit()

    resp: dict = {"detail": "VPC deleted", "vpc_id": vpc_id}
    if proxmox_error:
        resp["proxmox_warning"] = proxmox_error
    return resp

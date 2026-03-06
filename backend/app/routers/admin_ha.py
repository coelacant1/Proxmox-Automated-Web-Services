"""Admin HA group management + user HA instance endpoints."""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin, require_capability
from app.models.models import HAGroup, Resource, User
from app.services.proxmox_client import proxmox_client as pve

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Schemas ---

class HAGroupCreate(BaseModel):
    name: str
    description: str | None = None
    pve_group_name: str
    nodes: list[str]
    restricted: bool = False
    nofailback: bool = False
    max_relocate: int = 1
    max_restart: int = 1

class HAGroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    nodes: list[str] | None = None
    restricted: bool | None = None
    nofailback: bool | None = None
    max_relocate: int | None = None
    max_restart: int | None = None
    is_active: bool | None = None

class HAEnableRequest(BaseModel):
    ha_group_id: str | None = None
    max_relocate: int | None = None
    max_restart: int | None = None


# --- Admin endpoints ---

@router.get("/api/admin/ha/groups")
async def list_ha_groups(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    result = await db.execute(select(HAGroup).order_by(HAGroup.name))
    groups = result.scalars().all()
    return [_serialize_group(g) for g in groups]


@router.post("/api/admin/ha/groups", status_code=201)
async def create_ha_group(body: HAGroupCreate, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    # Check uniqueness
    existing = await db.execute(select(HAGroup).where(HAGroup.pve_group_name == body.pve_group_name))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "HA group with this PVE name already exists")

    # Create on PVE
    try:
        pve_params = {}
        if body.nofailback:
            pve_params["nofailback"] = 1
        pve.create_ha_group(body.pve_group_name, ",".join(body.nodes), **pve_params)
    except Exception as e:
        err = str(e)
        if "already exists" not in err.lower():
            raise HTTPException(502, f"Failed to create HA group on PVE: {err}")
        logger.info("HA group %s already exists on PVE, tracking in PAWS", body.pve_group_name)

    group = HAGroup(
        name=body.name,
        description=body.description,
        pve_group_name=body.pve_group_name,
        nodes=json.dumps(body.nodes),
        restricted=body.restricted,
        nofailback=body.nofailback,
        max_relocate=body.max_relocate,
        max_restart=body.max_restart,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return _serialize_group(group)


@router.patch("/api/admin/ha/groups/{group_id}")
async def update_ha_group(group_id: str, body: HAGroupUpdate, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    group = await db.get(HAGroup, uuid.UUID(group_id))
    if not group:
        raise HTTPException(404, "HA group not found")

    updates = body.model_dump(exclude_unset=True)
    pve_updates = {}

    if "nodes" in updates:
        group.nodes = json.dumps(updates.pop("nodes"))
        pve_updates["nodes"] = ",".join(json.loads(group.nodes))
    if "nofailback" in updates:
        group.nofailback = updates.pop("nofailback")
        pve_updates["nofailback"] = 1 if group.nofailback else 0

    for k, v in updates.items():
        if hasattr(group, k):
            setattr(group, k, v)

    # Sync to PVE
    if pve_updates:
        try:
            pve.update_ha_group(group.pve_group_name, **pve_updates)
        except Exception as e:
            raise HTTPException(502, f"Failed to update HA group on PVE: {e}")

    await db.commit()
    await db.refresh(group)
    return _serialize_group(group)


@router.delete("/api/admin/ha/groups/{group_id}")
async def delete_ha_group(group_id: str, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    group = await db.get(HAGroup, uuid.UUID(group_id))
    if not group:
        raise HTTPException(404, "HA group not found")

    try:
        pve.delete_ha_group(group.pve_group_name)
    except Exception as e:
        err = str(e)
        if "does not exist" not in err.lower() and "not found" not in err.lower():
            raise HTTPException(502, f"Failed to delete HA group on PVE: {err}")

    await db.delete(group)
    await db.commit()
    return {"detail": "HA group deleted"}


@router.post("/api/admin/ha/groups/sync")
async def sync_ha_groups(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    """Sync HA groups from PVE cluster into PAWS database."""
    try:
        pve_groups = pve.get_ha_groups()
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch HA groups from PVE: {e}")

    synced = 0
    for pg in pve_groups:
        group_name = pg.get("group", "")
        if not group_name:
            continue

        existing = await db.execute(select(HAGroup).where(HAGroup.pve_group_name == group_name))
        if existing.scalar_one_or_none():
            continue

        nodes_str = pg.get("nodes", "")
        nodes = [n.split(":")[0] for n in nodes_str.split(",") if n.strip()]

        group = HAGroup(
            name=group_name,
            pve_group_name=group_name,
            nodes=json.dumps(nodes),
            nofailback=bool(pg.get("nofailback", 0)),
            max_relocate=pg.get("max_relocate", 1) or 1,
            max_restart=pg.get("max_restart", 1) or 1,
        )
        db.add(group)
        synced += 1

    await db.commit()
    return {"detail": f"Synced {synced} new HA groups from PVE"}


# --- User HA endpoints (gated by ha.manage capability) ---

@router.get("/api/compute/instances/{resource_id}/ha")
async def get_instance_ha(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_capability("ha.manage")),
):
    resource = await _get_user_resource(db, user, resource_id)
    sid = _resource_to_sid(resource)

    try:
        ha_res = pve.get_ha_resource(sid)
        return {"enabled": True, "state": ha_res.get("state", "unknown"), "group": ha_res.get("group"), "sid": sid, "max_relocate": ha_res.get("max_relocate"), "max_restart": ha_res.get("max_restart")}
    except Exception:
        return {"enabled": False, "state": None, "group": None, "sid": sid}


@router.post("/api/compute/instances/{resource_id}/ha")
async def enable_instance_ha(
    resource_id: str,
    body: HAEnableRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_capability("ha.manage")),
):
    resource = await _get_user_resource(db, user, resource_id)
    sid = _resource_to_sid(resource)

    pve_group = None
    if body.ha_group_id:
        ha_group = await db.get(HAGroup, uuid.UUID(body.ha_group_id))
        if not ha_group or not ha_group.is_active:
            raise HTTPException(404, "HA group not found or inactive")
        pve_group = ha_group.pve_group_name

    kwargs = {}
    if body.max_relocate is not None:
        kwargs["max_relocate"] = body.max_relocate
    if body.max_restart is not None:
        kwargs["max_restart"] = body.max_restart

    try:
        pve.add_ha_resource(sid, group=pve_group, **kwargs)
    except Exception as e:
        err = str(e)
        if "already exists" in err.lower():
            raise HTTPException(409, "Instance is already HA-managed")
        raise HTTPException(502, f"Failed to enable HA: {err}")

    return {"detail": "HA enabled", "sid": sid}


@router.delete("/api/compute/instances/{resource_id}/ha")
async def disable_instance_ha(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_capability("ha.manage")),
):
    resource = await _get_user_resource(db, user, resource_id)
    sid = _resource_to_sid(resource)

    try:
        pve.remove_ha_resource(sid)
    except Exception as e:
        err = str(e)
        if "does not exist" not in err.lower() and "not found" not in err.lower():
            raise HTTPException(502, f"Failed to disable HA: {err}")

    return {"detail": "HA disabled"}


@router.get("/api/ha/groups")
async def list_user_ha_groups(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_capability("ha.manage")),
):
    """List active, non-restricted HA groups available to users."""
    result = await db.execute(
        select(HAGroup).where(HAGroup.is_active == True, HAGroup.restricted == False).order_by(HAGroup.name)  # noqa: E712
    )
    groups = result.scalars().all()
    return [{"id": str(g.id), "name": g.name, "description": g.description, "nodes": json.loads(g.nodes)} for g in groups]


# --- Helpers ---

def _serialize_group(g: HAGroup) -> dict:
    return {
        "id": str(g.id),
        "name": g.name,
        "description": g.description,
        "pve_group_name": g.pve_group_name,
        "nodes": json.loads(g.nodes),
        "restricted": g.restricted,
        "nofailback": g.nofailback,
        "max_relocate": g.max_relocate,
        "max_restart": g.max_restart,
        "is_active": g.is_active,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


async def _get_user_resource(db: AsyncSession, user: User, resource_id: str) -> Resource:
    resource = await db.get(Resource, uuid.UUID(resource_id))
    if not resource:
        raise HTTPException(404, "Resource not found")
    if str(resource.owner_id) != str(user.id) and user.role not in ("admin", "superuser"):
        raise HTTPException(403, "Not your resource")
    if resource.resource_type not in ("vm", "lxc"):
        raise HTTPException(400, "HA is only available for VMs and containers")
    return resource


def _resource_to_sid(resource: Resource) -> str:
    prefix = "vm" if resource.resource_type == "vm" else "ct"
    return f"{prefix}:{resource.proxmox_vmid}"

"""Admin endpoints for viewing and acknowledging drift events."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.models import DriftEvent, Resource, User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/drift", tags=["drift"])

# Drift types that can be auto-fixed by syncing the PAWS DB to match Proxmox state.
AUTO_FIXABLE_TYPES = {"status_mismatch", "node_mismatch"}

_PVE_STATUS_MAP = {
    "running": "running",
    "stopped": "stopped",
    "paused": "stopped",
    "suspended": "stopped",
}


@router.get("")
async def list_drift_events(
    acknowledged: bool | None = None,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List drift events. Pass ?acknowledged=false to see only active drift."""
    q = select(DriftEvent).order_by(DriftEvent.detected_at.desc()).limit(200)
    if acknowledged is not None:
        q = q.where(DriftEvent.acknowledged == acknowledged)
    result = await db.execute(q)
    events = result.scalars().all()

    resource_ids = {e.resource_id for e in events if e.resource_id}
    resource_names: dict[uuid.UUID, str] = {}
    if resource_ids:
        r_result = await db.execute(select(Resource).where(Resource.id.in_(resource_ids)))
        for r in r_result.scalars().all():
            resource_names[r.id] = r.display_name

    return [
        {
            "id": str(e.id),
            "detected_at": e.detected_at.isoformat() if e.detected_at else None,
            "resource_id": str(e.resource_id) if e.resource_id else None,
            "resource_name": resource_names.get(e.resource_id) if e.resource_id else None,
            "proxmox_vmid": e.proxmox_vmid,
            "proxmox_node": e.proxmox_node,
            "drift_type": e.drift_type,
            "details": e.details,
            "acknowledged": e.acknowledged,
            "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None,
            "auto_fixable": e.drift_type in AUTO_FIXABLE_TYPES and e.resource_id is not None,
        }
        for e in events
    ]


@router.post("/{event_id}/fix")
async def fix_drift_event(
    event_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Auto-fix an auto-fixable drift event by syncing PAWS DB to current Proxmox state.

    Supported drift types: status_mismatch, node_mismatch. PVE is treated as the
    source of truth (e.g., the user started/stopped a VM directly on Proxmox, or
    HA migrated it to a different node).
    """
    from app.services.cluster_registry import NoClustersConfigured, cluster_registry
    from app.services.proxmox_client import get_pve

    result = await db.execute(select(DriftEvent).where(DriftEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Drift event not found")
    if event.drift_type not in AUTO_FIXABLE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Drift type '{event.drift_type}' is not auto-fixable",
        )
    if not event.resource_id:
        raise HTTPException(status_code=400, detail="Event has no associated resource")

    resource_q = await db.execute(select(Resource).where(Resource.id == event.resource_id))
    resource = resource_q.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Associated resource no longer exists")
    if not resource.proxmox_vmid:
        raise HTTPException(status_code=400, detail="Resource has no proxmox_vmid")

    if not cluster_registry.has_clusters():
        await cluster_registry.reload()
    try:
        pve = get_pve()
    except NoClustersConfigured as exc:
        raise HTTPException(status_code=503, detail="No Proxmox cluster configured") from exc

    try:
        pve_resources = await asyncio.to_thread(pve.get_cluster_resources)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query Proxmox: {exc}") from exc

    pve_r = next(
        (
            r
            for r in pve_resources
            if r.get("type") in ("qemu", "lxc") and int(r.get("vmid", 0)) == resource.proxmox_vmid
        ),
        None,
    )
    if not pve_r:
        raise HTTPException(
            status_code=409,
            detail="VMID no longer exists in Proxmox; this is now an orphaned_in_db event",
        )

    pve_status = _PVE_STATUS_MAP.get(pve_r.get("status", ""), "stopped")
    pve_node = pve_r.get("node", "") or resource.proxmox_node

    changes: dict[str, Any] = {}
    if event.drift_type == "status_mismatch" and resource.status != pve_status:
        changes["status"] = {"from": resource.status, "to": pve_status}
        resource.status = pve_status
    if event.drift_type == "node_mismatch" and pve_node and resource.proxmox_node != pve_node:
        changes["proxmox_node"] = {"from": resource.proxmox_node, "to": pve_node}
        resource.proxmox_node = pve_node

    # Resolve the event by deleting it (next scan would do the same).
    await db.delete(event)
    await db.commit()
    log.info("Drift event %s auto-fixed: %s", event_id, json.dumps(changes))
    return {"id": str(event_id), "fixed": True, "changes": changes}


@router.post("/fix-all")
async def fix_all_auto_fixable(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Auto-fix every active auto-fixable drift event by syncing DB to PVE."""
    from app.services.cluster_registry import NoClustersConfigured, cluster_registry
    from app.services.proxmox_client import get_pve

    q = await db.execute(
        select(DriftEvent).where(
            DriftEvent.acknowledged.is_(False),
            DriftEvent.drift_type.in_(list(AUTO_FIXABLE_TYPES)),
            DriftEvent.resource_id.isnot(None),
        )
    )
    events = list(q.scalars().all())
    if not events:
        return {"fixed": 0, "skipped": 0}

    if not cluster_registry.has_clusters():
        await cluster_registry.reload()
    try:
        pve = get_pve()
    except NoClustersConfigured as exc:
        raise HTTPException(status_code=503, detail="No Proxmox cluster configured") from exc
    try:
        pve_resources = await asyncio.to_thread(pve.get_cluster_resources)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query Proxmox: {exc}") from exc

    pve_by_vmid = {int(r["vmid"]): r for r in pve_resources if r.get("type") in ("qemu", "lxc")}

    resource_ids = [e.resource_id for e in events if e.resource_id]
    res_q = await db.execute(select(Resource).where(Resource.id.in_(resource_ids)))
    resources_by_id = {r.id: r for r in res_q.scalars().all()}

    fixed = 0
    skipped = 0
    for ev in events:
        resource = resources_by_id.get(ev.resource_id)
        if not resource or not resource.proxmox_vmid:
            skipped += 1
            continue
        pve_r = pve_by_vmid.get(resource.proxmox_vmid)
        if not pve_r:
            skipped += 1
            continue
        pve_status = _PVE_STATUS_MAP.get(pve_r.get("status", ""), "stopped")
        pve_node = pve_r.get("node", "") or resource.proxmox_node
        changed = False
        if ev.drift_type == "status_mismatch" and resource.status != pve_status:
            resource.status = pve_status
            changed = True
        if ev.drift_type == "node_mismatch" and pve_node and resource.proxmox_node != pve_node:
            resource.proxmox_node = pve_node
            changed = True
        if changed or resource.status == pve_status:
            await db.delete(ev)
            fixed += 1
        else:
            skipped += 1

    await db.commit()
    log.info("Drift fix-all: %d fixed, %d skipped", fixed, skipped)
    return {"fixed": fixed, "skipped": skipped}


@router.post("/{event_id}/acknowledge")
async def acknowledge_drift_event(
    event_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mark a drift event as acknowledged."""
    result = await db.execute(select(DriftEvent).where(DriftEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Drift event not found")
    event.acknowledged = True
    event.acknowledged_at = datetime.now(UTC)
    event.acknowledged_by = admin.id
    await db.commit()
    return {"id": str(event.id), "acknowledged": True}


@router.delete("/{event_id}")
async def delete_drift_event(
    event_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a single drift event."""
    result = await db.execute(select(DriftEvent).where(DriftEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Drift event not found")
    await db.delete(event)
    await db.commit()
    return {"detail": "Deleted"}

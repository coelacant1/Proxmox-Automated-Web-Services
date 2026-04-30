"""Background drift scanner: detects divergence between the PAWS DB and Proxmox cluster.

Runs every 5 minutes via Celery Beat. Records findings in the drift_events table.
Previous unacknowledged events of the same type+resource are replaced on each scan
to avoid unbounded growth.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from celery import shared_task

log = logging.getLogger(__name__)

_PVE_STATUS_MAP = {
    "running": "running",
    "stopped": "stopped",
    "paused": "stopped",
    "suspended": "stopped",
}


def _run_async(coro):
    from app.tasks._async_runner import run_task_async

    return run_task_async(coro)


async def _scan() -> dict:
    import uuid

    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.models import DriftEvent, Resource
    from app.routers.resources import parse_paws_id
    from app.services.cluster_registry import NoClustersConfigured, cluster_registry
    from app.services.proxmox_client import get_pve

    if not cluster_registry.has_clusters():
        await cluster_registry.reload()

    try:
        pve = get_pve()
    except NoClustersConfigured:
        log.debug("Drift scan skipped: no cluster configured")
        return {"skipped": True}

    try:
        pve_resources = pve.get_cluster_resources()
    except Exception as exc:
        log.warning("Drift scan: failed to list Proxmox resources: %s", exc)
        return {"error": str(exc)}

    pve_by_vmid: dict[int, dict] = {}
    for r in pve_resources:
        if r.get("type") in ("qemu", "lxc"):
            pve_by_vmid[int(r["vmid"])] = r

    async with async_session() as db:
        result = await db.execute(
            select(Resource).where(
                Resource.resource_type.in_(["vm", "lxc"]),
                Resource.status.notin_(["deleted", "terminated", "error"]),
                Resource.proxmox_vmid.isnot(None),
            )
        )
        db_resources = list(result.scalars().all())

        db_vmids = {r.proxmox_vmid for r in db_resources}
        pve_vmids = set(pve_by_vmid.keys())

        events_to_upsert: list[dict] = []
        auto_fixed = 0

        for r in db_resources:
            if r.proxmox_vmid not in pve_vmids:
                events_to_upsert.append(
                    {
                        "resource_id": str(r.id),
                        "proxmox_vmid": r.proxmox_vmid,
                        "proxmox_node": r.proxmox_node,
                        "drift_type": "orphaned_in_db",
                        "details": json.dumps({"db_status": r.status, "db_node": r.proxmox_node}),
                    }
                )

        for r in db_resources:
            pve_r = pve_by_vmid.get(r.proxmox_vmid)
            if not pve_r:
                continue
            pve_status = _PVE_STATUS_MAP.get(pve_r.get("status", ""), "stopped")
            pve_node = pve_r.get("node", "")

            # Auto-correct status_mismatch by syncing DB to PVE (PVE is source of truth).
            if r.status in ("running", "stopped") and r.status != pve_status:
                log.info(
                    "Drift auto-fix status_mismatch: resource=%s vmid=%s db=%s -> pve=%s",
                    r.id,
                    r.proxmox_vmid,
                    r.status,
                    pve_status,
                )
                r.status = pve_status
                auto_fixed += 1

            # Auto-correct node_mismatch (e.g., after live migration) by syncing DB to PVE.
            if r.proxmox_node and pve_node and r.proxmox_node != pve_node:
                log.info(
                    "Drift auto-fix node_mismatch: resource=%s vmid=%s db=%s -> pve=%s",
                    r.id,
                    r.proxmox_vmid,
                    r.proxmox_node,
                    pve_node,
                )
                r.proxmox_node = pve_node
                auto_fixed += 1

        for vmid, pve_r in pve_by_vmid.items():
            if vmid in db_vmids:
                continue
            desc = pve_r.get("description") or pve_r.get("notes") or ""
            paws_id = parse_paws_id(desc)
            if paws_id:
                events_to_upsert.append(
                    {
                        "resource_id": None,
                        "proxmox_vmid": vmid,
                        "proxmox_node": pve_r.get("node"),
                        "drift_type": "orphaned_in_proxmox",
                        "details": json.dumps({"paws_id": paws_id, "pve_name": pve_r.get("name", "")}),
                    }
                )

        now = datetime.now(UTC)
        inserted = 0
        resolved = 0

        current_event_keys = {(e["resource_id"], e["drift_type"]) for e in events_to_upsert}

        existing_result = await db.execute(select(DriftEvent).where(DriftEvent.acknowledged.is_(False)))
        for existing in existing_result.scalars().all():
            key = (str(existing.resource_id) if existing.resource_id else None, existing.drift_type)
            if key not in current_event_keys:
                await db.delete(existing)
                resolved += 1

        for ev in events_to_upsert:
            existing_q = await db.execute(
                select(DriftEvent).where(
                    DriftEvent.drift_type == ev["drift_type"],
                    DriftEvent.acknowledged.is_(False),
                    DriftEvent.resource_id == (uuid.UUID(ev["resource_id"]) if ev["resource_id"] else None),
                )
            )
            existing_event = existing_q.scalar_one_or_none()
            if existing_event:
                existing_event.detected_at = now
                existing_event.proxmox_vmid = ev["proxmox_vmid"]
                existing_event.proxmox_node = ev["proxmox_node"]
                existing_event.details = ev["details"]
            else:
                new_event = DriftEvent(
                    id=uuid.uuid4(),
                    detected_at=now,
                    resource_id=uuid.UUID(ev["resource_id"]) if ev["resource_id"] else None,
                    proxmox_vmid=ev["proxmox_vmid"],
                    proxmox_node=ev["proxmox_node"],
                    drift_type=ev["drift_type"],
                    details=ev["details"],
                    acknowledged=False,
                )
                db.add(new_event)
                inserted += 1

        await db.commit()
        log.info(
            "Drift scan complete: %d new events, %d resolved, %d auto-fixed",
            inserted,
            resolved,
            auto_fixed,
        )
        return {"inserted": inserted, "resolved": resolved, "auto_fixed": auto_fixed}


@shared_task(name="paws.scan_drift")
def scan_drift():
    return _run_async(_scan())

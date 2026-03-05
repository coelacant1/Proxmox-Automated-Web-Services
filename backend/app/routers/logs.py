"""Log aggregation API - query and search Proxmox task logs and syslog."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import Resource, User
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/tasks/{resource_id}")
async def get_resource_task_logs(
    resource_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get Proxmox task logs for a resource."""
    result = await db.execute(
        select(Resource).where(Resource.id == uuid.UUID(resource_id), Resource.owner_id == user.id)
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    try:
        tasks = proxmox_client.get_node_tasks(resource.proxmox_node, vmid=resource.proxmox_vmid)
        return {"resource_id": resource_id, "tasks": tasks[:limit]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/tasks/{resource_id}/{upid}")
async def get_task_detail(
    resource_id: str,
    upid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get detailed log output for a specific task."""
    result = await db.execute(
        select(Resource).where(Resource.id == uuid.UUID(resource_id), Resource.owner_id == user.id)
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    try:
        task_status = proxmox_client.get_task_status(resource.proxmox_node, upid)
        return {"upid": upid, "detail": task_status}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/cluster")
async def get_cluster_logs(
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_admin),
):
    """Get cluster-wide task logs (admin only)."""
    try:
        nodes = proxmox_client.get_nodes()
        all_tasks = []
        for node_info in nodes[:5]:
            node_name = node_info.get("node", "")
            tasks = proxmox_client.get_node_tasks(node_name)
            for t in tasks:
                t["node"] = node_name
            all_tasks.extend(tasks)

        all_tasks.sort(key=lambda t: t.get("starttime", 0), reverse=True)
        return {"tasks": all_tasks[:limit]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/search")
async def search_logs(
    q: str = Query(..., min_length=1, max_length=200),
    source: str | None = None,
    severity: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Full-text search across audit logs and events."""
    from app.models.models import AuditLog, Event

    results: list[dict] = []

    # Search audit logs
    audit_query = select(AuditLog).where(
        AuditLog.user_id == user.id,
        AuditLog.action.ilike(f"%{q}%"),
    ).order_by(AuditLog.created_at.desc()).limit(limit)
    audit_result = await db.execute(audit_query)
    for log in audit_result.scalars().all():
        results.append({
            "type": "audit",
            "action": log.action,
            "resource_type": log.resource_type,
            "created_at": str(log.created_at),
        })

    # Search events
    event_query = select(Event).where(Event.message.ilike(f"%{q}%"))
    if source:
        event_query = event_query.where(Event.source == source)
    if severity:
        event_query = event_query.where(Event.severity == severity)
    event_query = event_query.order_by(Event.created_at.desc()).limit(limit)
    event_result = await db.execute(event_query)
    for e in event_result.scalars().all():
        results.append({
            "type": "event",
            "event_type": e.event_type,
            "source": e.source,
            "severity": e.severity,
            "message": e.message,
            "created_at": str(e.created_at),
        })

    return {"query": q, "total": len(results), "results": results[:limit]}

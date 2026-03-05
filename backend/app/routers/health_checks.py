"""Health check API - resource health monitoring and guest agent integration."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import HealthCheck, Resource, User
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/{resource_id}")
async def get_resource_health(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get latest health check results for a resource."""
    resource = await _get_user_resource(db, user.id, resource_id)

    result = await db.execute(
        select(HealthCheck)
        .where(HealthCheck.resource_id == resource.id)
        .order_by(HealthCheck.checked_at.desc())
        .limit(10)
    )
    checks = result.scalars().all()
    return {
        "resource_id": str(resource.id),
        "status": resource.status,
        "checks": [
            {
                "id": str(c.id),
                "check_type": c.check_type,
                "status": c.status,
                "latency_ms": c.latency_ms,
                "details": c.details,
                "checked_at": str(c.checked_at),
            }
            for c in checks
        ],
    }


@router.post("/{resource_id}/check")
async def run_health_check(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Trigger an on-demand health check for a resource."""
    resource = await _get_user_resource(db, user.id, resource_id)

    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
    try:
        if vmtype == "lxc":
            status_data = proxmox_client.get_container_status(resource.proxmox_node, resource.proxmox_vmid)
        else:
            status_data = proxmox_client.get_vm_status(resource.proxmox_node, resource.proxmox_vmid)

        vm_status = status_data.get("status", "unknown")
        health = "healthy" if vm_status == "running" else "unhealthy"

        check = HealthCheck(
            resource_id=resource.id,
            check_type="agent",
            status=health,
            details=json.dumps({"vm_status": vm_status, "uptime": status_data.get("uptime", 0)}),
        )
        db.add(check)
        await db.commit()

        return {
            "resource_id": str(resource.id),
            "status": health,
            "vm_status": vm_status,
            "check_id": str(check.id),
        }
    except Exception as e:
        check = HealthCheck(
            resource_id=resource.id,
            check_type="agent",
            status="unhealthy",
            details=str(e),
        )
        db.add(check)
        await db.commit()
        return {
            "resource_id": str(resource.id),
            "status": "unhealthy",
            "error": str(e),
        }


@router.get("/{resource_id}/agent")
async def get_guest_agent_info(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get QEMU guest agent information for a VM."""
    resource = await _get_user_resource(db, user.id, resource_id)

    if resource.resource_type == "lxc":
        raise HTTPException(status_code=400, detail="Guest agent not available for containers")

    try:
        agent_info = proxmox_client.get_agent_info(resource.proxmox_node, resource.proxmox_vmid)
        return {
            "resource_id": str(resource.id),
            "agent_available": True,
            "info": agent_info,
        }
    except Exception:
        return {
            "resource_id": str(resource.id),
            "agent_available": False,
            "info": None,
        }


# --- Helpers ---


async def _get_user_resource(db: AsyncSession, user_id: uuid.UUID, resource_id: str) -> Resource:
    result = await db.execute(
        select(Resource).where(
            Resource.id == uuid.UUID(resource_id),
            Resource.owner_id == user_id,
            Resource.status != "destroyed",
        )
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource

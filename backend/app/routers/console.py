"""Console access API - VNC (noVNC), terminal (xterm.js), and SPICE proxy tickets.

Generates Proxmox proxy tickets that the frontend uses to establish
WebSocket connections for interactive console access.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import Resource, User
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/console", tags=["console"])

CONSOLE_TYPES = {"vnc", "terminal", "spice"}


@router.post("/{resource_id}/vnc")
async def get_vnc_console(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get a VNC proxy ticket for noVNC web console."""
    resource = await _get_running_resource(db, user.id, resource_id)
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"

    try:
        ticket_data = proxmox_client.get_vnc_ticket(
            resource.proxmox_node, resource.proxmox_vmid, vmtype
        )
        return {
            "type": "vnc",
            "ticket": ticket_data.get("ticket"),
            "port": ticket_data.get("port"),
            "node": resource.proxmox_node,
            "vmid": resource.proxmox_vmid,
            "websocket_url": _build_ws_url(resource, "vncwebsocket", ticket_data),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{resource_id}/terminal")
async def get_terminal_console(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get a terminal proxy ticket for xterm.js serial console."""
    resource = await _get_running_resource(db, user.id, resource_id)
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"

    try:
        ticket_data = proxmox_client.get_terminal_proxy(
            resource.proxmox_node, resource.proxmox_vmid, vmtype
        )
        return {
            "type": "terminal",
            "ticket": ticket_data.get("ticket"),
            "port": ticket_data.get("port"),
            "node": resource.proxmox_node,
            "vmid": resource.proxmox_vmid,
            "websocket_url": _build_ws_url(resource, "termproxy", ticket_data),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{resource_id}/spice")
async def get_spice_console(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get a SPICE proxy ticket for remote desktop."""
    resource = await _get_running_resource(db, user.id, resource_id)
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"

    try:
        ticket_data = proxmox_client.get_spice_ticket(
            resource.proxmox_node, resource.proxmox_vmid, vmtype
        )
        return {
            "type": "spice",
            "ticket": ticket_data.get("ticket"),
            "proxy": ticket_data.get("proxy"),
            "node": resource.proxmox_node,
            "vmid": resource.proxmox_vmid,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{resource_id}/available")
async def get_available_consoles(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List available console types for a resource."""
    resource = await _get_running_resource(db, user.id, resource_id)
    consoles = ["vnc", "terminal"]
    if resource.resource_type != "lxc":
        consoles.append("spice")
    return {"resource_id": resource_id, "available": consoles}


# --- Helpers ---


def _build_ws_url(resource: Resource, proxy_type: str, ticket_data: dict) -> str:
    """Build WebSocket URL for proxying through Proxmox."""
    from app.core.config import settings

    host = settings.proxmox_host
    port = settings.proxmox_port
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
    vncticket = ticket_data.get("ticket", "")
    return (
        f"wss://{host}:{port}/api2/json/nodes/{resource.proxmox_node}"
        f"/{vmtype}/{resource.proxmox_vmid}/{proxy_type}"
        f"?port={ticket_data.get('port', 0)}&vncticket={vncticket}"
    )


async def _get_running_resource(db: AsyncSession, user_id: uuid.UUID, resource_id: str) -> Resource:
    result = await db.execute(
        select(Resource).where(
            Resource.id == uuid.UUID(resource_id),
            Resource.owner_id == user_id,
        )
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    if resource.status != "running":
        raise HTTPException(status_code=409, detail="Resource must be running for console access")
    return resource

"""SDN / networking management endpoints."""

import ipaddress
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import VPC, IPReservation, Resource, Subnet, User, UserTier
from app.schemas.schemas import (
    BandwidthUpdate,
    IPReservationRead,
    NetworkModeRead,
    NetworkModeUpdate,
)
from app.services.audit_service import log_action
from app.services.firewall_profile import FirewallProfileService
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/networking", tags=["networking"])


# --- SDN Zone / VNet browsing (admin) ---


class VNetCreateRequest(BaseModel):
    name: str
    zone: str
    tag: int | None = None
    alias: str | None = None


class FirewallRuleRequest(BaseModel):
    direction: str = "in"
    action: str = "ACCEPT"
    proto: str | None = None
    dport: str | None = None
    sport: str | None = None
    source: str | None = None
    dest: str | None = None
    comment: str | None = None
    enable: int = 1


@router.get("/zones")
async def list_zones(_: User = Depends(get_current_active_user)):
    try:
        return proxmox_client.get_sdn_zones()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/vnets")
async def list_vnets(_: User = Depends(get_current_active_user)):
    try:
        return proxmox_client.get_sdn_vnets()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/vnets", status_code=status.HTTP_201_CREATED)
async def create_vnet(
    body: VNetCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    try:
        kwargs = {}
        if body.tag is not None:
            kwargs["tag"] = body.tag
        if body.alias:
            kwargs["alias"] = body.alias
        proxmox_client.create_sdn_vnet(body.name, body.zone, **kwargs)
        await log_action(db, user.id, "vnet_create", "network", details={"vnet": body.name, "zone": body.zone})
        return {"status": "created", "vnet": body.name}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/vnets/{vnet_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vnet(
    vnet_name: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    try:
        proxmox_client.delete_sdn_vnet(vnet_name)
        await log_action(db, user.id, "vnet_delete", "network", details={"vnet": vnet_name})
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- VM/Container Firewall ---


@router.get("/vms/{node}/{vmid}/firewall")
async def get_firewall_rules(
    node: str,
    vmid: int,
    _: User = Depends(get_current_active_user),
):
    try:
        return proxmox_client.get_firewall_rules(node, vmid, "qemu")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/vms/{node}/{vmid}/firewall")
async def add_firewall_rule(
    node: str,
    vmid: int,
    body: FirewallRuleRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    try:
        params = {
            "type": body.direction,
            "action": body.action,
            "enable": body.enable,
        }
        for field in ("proto", "dport", "sport", "source", "dest", "comment"):
            val = getattr(body, field)
            if val is not None:
                params[field] = val

        proxmox_client.create_firewall_rule(node, vmid, "qemu", **params)
        await log_action(db, user.id, "firewall_add", "vm", details={"vmid": vmid, "rule": params})
        return {"status": "created"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- DB-backed IP Reservations ---


class StaticIPRequest(BaseModel):
    subnet_id: str  # UUID of the subnet
    ip_address: str | None = None  # auto-assign if None
    resource_id: str | None = None
    label: str | None = None


@router.post("/vpcs/{vpc_id}/ips", response_model=IPReservationRead)
async def reserve_static_ip(
    vpc_id: str,
    body: StaticIPRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Reserve a static IP address within a VPC subnet."""
    # Verify subnet belongs to user's VPC
    subnet_result = await db.execute(
        select(Subnet)
        .join(VPC, Subnet.vpc_id == VPC.id)
        .where(Subnet.id == _uuid.UUID(body.subnet_id), VPC.id == _uuid.UUID(vpc_id), VPC.owner_id == user.id)
        .options(selectinload(Subnet.ip_reservations))
    )
    subnet = subnet_result.scalar_one_or_none()
    if not subnet:
        raise HTTPException(status_code=404, detail="Subnet not found")

    try:
        network = ipaddress.ip_network(subnet.cidr, strict=False)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid subnet CIDR")

    used_ips = {r.ip_address for r in subnet.ip_reservations}

    if body.ip_address:
        ip = body.ip_address
        if ip in used_ips:
            raise HTTPException(status_code=409, detail="IP already reserved")
        if ipaddress.ip_address(ip) not in network:
            raise HTTPException(status_code=400, detail="IP not in subnet range")
    else:
        # Auto-assign: skip gateway (.1) and already reserved
        ip = None
        for host in list(network.hosts())[1:]:
            if str(host) not in used_ips:
                ip = str(host)
                break
        if not ip:
            raise HTTPException(status_code=409, detail="No available IPs in subnet")

    reservation = IPReservation(
        subnet_id=subnet.id,
        ip_address=ip,
        resource_id=_uuid.UUID(body.resource_id) if body.resource_id else None,
        label=body.label,
        is_gateway=False,
        owner_id=user.id,
    )
    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)
    await log_action(db, user.id, "ip_reserve", "network", details={"ip": ip, "subnet_id": body.subnet_id})
    return reservation


@router.get("/vpcs/{vpc_id}/ips", response_model=list[IPReservationRead])
async def list_static_ips(
    vpc_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List reserved static IPs in a VPC."""
    result = await db.execute(
        select(IPReservation)
        .join(Subnet, IPReservation.subnet_id == Subnet.id)
        .join(VPC, Subnet.vpc_id == VPC.id)
        .where(VPC.id == _uuid.UUID(vpc_id), IPReservation.owner_id == user.id)
    )
    return list(result.scalars().all())


@router.delete("/vpcs/{vpc_id}/ips/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def release_static_ip(
    vpc_id: str,
    reservation_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Release a reserved static IP."""
    result = await db.execute(
        select(IPReservation)
        .join(Subnet, IPReservation.subnet_id == Subnet.id)
        .join(VPC, Subnet.vpc_id == VPC.id)
        .where(
            IPReservation.id == _uuid.UUID(reservation_id),
            VPC.id == _uuid.UUID(vpc_id),
            IPReservation.owner_id == user.id,
        )
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="IP reservation not found")
    if reservation.resource_id:
        raise HTTPException(status_code=400, detail="Cannot release IP bound to a resource")

    ip = reservation.ip_address
    await db.delete(reservation)
    await db.commit()
    await log_action(db, user.id, "ip_release", "network", details={"ip": ip, "vpc_id": vpc_id})


# --- Network Mode ---


@router.get("/instances/{resource_id}/network-mode", response_model=NetworkModeRead)
async def get_network_mode(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get the network mode and bandwidth for an instance.

    The network mode is derived from the instance's primary VPC.
    """
    import json as _json

    resource = await _get_user_resource(db, user, resource_id)

    # Derive mode from primary VPC
    specs = resource.specs
    if isinstance(specs, str):
        try:
            specs = _json.loads(specs)
        except (ValueError, TypeError):
            specs = {}
    vpc_id = specs.get("vpc_id") if isinstance(specs, dict) else None
    vpc_mode = "private"
    vpc_name = None
    if vpc_id:
        vpc_row = await db.execute(select(VPC).where(VPC.id == _uuid.UUID(vpc_id)))
        vpc = vpc_row.scalar_one_or_none()
        if vpc:
            vpc_mode = vpc.network_mode or "private"
            vpc_name = vpc.name

    tier = await _get_user_tier(db, user.id)
    effective_bw = FirewallProfileService.get_effective_bandwidth(
        tier.bandwidth_limit_mbps if tier else None,
        resource.bandwidth_limit_mbps,
    )
    return {
        "network_mode": vpc_mode,
        "bandwidth_limit_mbps": resource.bandwidth_limit_mbps,
        "effective_bandwidth_mbps": effective_bw,
        "vpc_name": vpc_name,
        "vpc_id": vpc_id,
    }


@router.put("/instances/{resource_id}/network-mode")
async def update_network_mode(
    resource_id: str,
    body: NetworkModeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Change the network mode for an instance.

    Network mode is now a per-network property.
    This endpoint changes the mode of the instance's primary VPC.
    """
    import json as _json

    if body.network_mode not in ("published", "private", "isolated"):
        raise HTTPException(status_code=400, detail="Invalid network mode")

    resource = await _get_user_resource(db, user, resource_id)

    # Find the instance's primary VPC
    specs = resource.specs
    if isinstance(specs, str):
        try:
            specs = _json.loads(specs)
        except (ValueError, TypeError):
            specs = {}
    vpc_id = specs.get("vpc_id") if isinstance(specs, dict) else None
    if not vpc_id:
        raise HTTPException(status_code=400, detail="Instance has no network attached")

    vpc_row = await db.execute(select(VPC).where(VPC.id == _uuid.UUID(vpc_id), VPC.owner_id == user.id))
    vpc = vpc_row.scalar_one_or_none()
    if not vpc:
        raise HTTPException(status_code=404, detail="Network not found")

    if vpc.network_mode == body.network_mode:
        tier = await _get_user_tier(db, user.id)
        effective_bw = FirewallProfileService.get_effective_bandwidth(
            tier.bandwidth_limit_mbps if tier else None,
            resource.bandwidth_limit_mbps,
        )
        return NetworkModeRead(
            network_mode=vpc.network_mode,
            bandwidth_limit_mbps=resource.bandwidth_limit_mbps,
            effective_bandwidth_mbps=effective_bw,
        )

    # Delegate to the VPC mode change logic
    from app.routers.vpcs import VPCModeUpdate, update_vpc_mode

    await update_vpc_mode(vpc_id, VPCModeUpdate(network_mode=body.network_mode), db, user)

    tier = await _get_user_tier(db, user.id)
    effective_bw = FirewallProfileService.get_effective_bandwidth(
        tier.bandwidth_limit_mbps if tier else None,
        resource.bandwidth_limit_mbps,
    )
    await log_action(
        db,
        user.id,
        "network_mode_change",
        resource.resource_type,
        resource_id=resource.id,
        details={"mode": body.network_mode},
    )
    return NetworkModeRead(
        network_mode=body.network_mode,
        bandwidth_limit_mbps=resource.bandwidth_limit_mbps,
        effective_bandwidth_mbps=effective_bw,
    )


@router.put("/instances/{resource_id}/bandwidth", response_model=NetworkModeRead)
async def update_bandwidth(
    resource_id: str,
    body: BandwidthUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Set per-instance bandwidth override (admin only)."""
    result = await db.execute(select(Resource).where(Resource.id == _uuid.UUID(resource_id)))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    node = resource.node
    vmid = resource.proxmox_vmid
    vmtype = "lxc" if resource.resource_type == "container" else "qemu"

    tier = await _get_user_tier(db, resource.owner_id)
    effective_bw = FirewallProfileService.get_effective_bandwidth(
        tier.bandwidth_limit_mbps if tier else None,
        body.bandwidth_limit_mbps,
    )

    FirewallProfileService.apply_bandwidth_limit(node, vmid, vmtype, effective_bw)

    resource.bandwidth_limit_mbps = body.bandwidth_limit_mbps
    await db.commit()

    await log_action(
        db,
        user.id,
        "bandwidth_change",
        resource.resource_type,
        resource_id=resource.id,
        details={"bandwidth_mbps": effective_bw},
    )
    return NetworkModeRead(
        network_mode=resource.network_mode or "private",
        bandwidth_limit_mbps=resource.bandwidth_limit_mbps,
        effective_bandwidth_mbps=effective_bw,
    )


# --- Helpers ---


async def _get_user_resource(db: AsyncSession, user: User, resource_id: str) -> Resource:
    """Get a resource owned by the user."""
    result = await db.execute(
        select(Resource).where(Resource.id == _uuid.UUID(resource_id), Resource.owner_id == user.id)
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


async def _get_user_tier(db: AsyncSession, user_id: _uuid.UUID) -> UserTier | None:
    """Get the user's tier for bandwidth defaults."""
    result = await db.execute(select(UserTier).join(User, User.tier_id == UserTier.id).where(User.id == user_id))
    return result.scalar_one_or_none()


async def _get_resource_subnet_cidr(db: AsyncSession, resource: Resource) -> str | None:
    """Extract the subnet CIDR for a resource from its VPC."""
    import json

    specs = resource.specs
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except (json.JSONDecodeError, TypeError):
            return None

    vpc_id = specs.get("vpc_id") if isinstance(specs, dict) else None
    if not vpc_id:
        return None

    result = await db.execute(select(Subnet).join(VPC, Subnet.vpc_id == VPC.id).where(VPC.id == _uuid.UUID(vpc_id)))
    subnet = result.scalars().first()
    return subnet.cidr if subnet else None

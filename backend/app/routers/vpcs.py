"""VPC and subnet management API with Proxmox SDN integration."""

import ipaddress
import json
import logging
import uuid as _uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import (
    VPC,
    IPReservation,
    Resource,
    ResourceSecurityGroup,
    SecurityGroup,
    SecurityGroupRule,
    Subnet,
    SystemSetting,
    User,
    UserQuota,
    UserTier,
)
from app.schemas.schemas import SubnetRead, VPCCreate, VPCRead
from app.services.audit_service import log_action
from app.services.group_access import check_group_access
from app.services.ipam_service import cidr_pool, ipam_service
from app.services.proxmox_client import get_pve
from app.services.sdn_service import sdn_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vpcs", tags=["vpcs"])


# ---------------------------------------------------------------------------
# Helper: auto-create a managed security group for published networks
# ---------------------------------------------------------------------------

_BOGON_RANGES = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
]


async def _ensure_published_sg(
    db: AsyncSession,
    owner_id: _uuid.UUID,
    vpc_name: str,
    vpc_cidr: str,
    cluster_id: str = "default",
) -> SecurityGroup:
    """Create a managed security group with bogon-blocking rules for a published network.

    Rules generated:
      1. ALLOW ingress/egress from own subnet (vpc_cidr)
      2. ALLOW ingress/egress from each upstream proxy IP (sdn.upstream_ips)
      3. DROP ingress/egress for every bogon/RFC1918 range
      4. ALLOW all remaining traffic (internet)
    """
    sg_name = f"Published: {vpc_name}"

    # Load upstream IPs from system settings
    from app.services.firewall_profile import FirewallProfileService

    upstream_ips = await FirewallProfileService.get_upstream_ips_async(db)

    sg = SecurityGroup(
        owner_id=owner_id,
        name=sg_name,
        description=(
            f"Auto-managed firewall for published network '{vpc_name}'."
            " Blocks bogon/RFC1918 traffic except own subnet and upstream proxies."
        ),
        cluster_id=cluster_id,
    )
    db.add(sg)
    await db.flush()

    rules: list[SecurityGroupRule] = []

    # 1. Allow own subnet
    for direction in ("ingress", "egress"):
        rules.append(
            SecurityGroupRule(
                security_group_id=sg.id,
                direction=direction,
                protocol="tcp",
                port_from=None,
                port_to=None,
                cidr=vpc_cidr,
                description=f"Allow {direction} from own subnet",
            )
        )
        rules.append(
            SecurityGroupRule(
                security_group_id=sg.id,
                direction=direction,
                protocol="udp",
                port_from=None,
                port_to=None,
                cidr=vpc_cidr,
                description=f"Allow {direction} from own subnet",
            )
        )
        rules.append(
            SecurityGroupRule(
                security_group_id=sg.id,
                direction=direction,
                protocol="icmp",
                port_from=None,
                port_to=None,
                cidr=vpc_cidr,
                description=f"Allow {direction} from own subnet",
            )
        )

    # 2. Allow upstream proxy IPs
    for ip in upstream_ips:
        for direction in ("ingress", "egress"):
            rules.append(
                SecurityGroupRule(
                    security_group_id=sg.id,
                    direction=direction,
                    protocol="tcp",
                    port_from=None,
                    port_to=None,
                    cidr=ip if "/" in ip else f"{ip}/32",
                    description=f"Allow upstream proxy {ip}",
                )
            )

    # 3. Block bogon ranges
    for bogon in _BOGON_RANGES:
        for direction in ("ingress", "egress"):
            rules.append(
                SecurityGroupRule(
                    security_group_id=sg.id,
                    direction=direction,
                    protocol="tcp",
                    port_from=None,
                    port_to=None,
                    cidr=bogon,
                    description=f"Block bogon {bogon}",
                )
            )
            rules.append(
                SecurityGroupRule(
                    security_group_id=sg.id,
                    direction=direction,
                    protocol="udp",
                    port_from=None,
                    port_to=None,
                    cidr=bogon,
                    description=f"Block bogon {bogon}",
                )
            )

    for r in rules:
        db.add(r)

    return sg


# Helpers
# ---------------------------------------------------------------------------


async def _get_vpc(
    db: AsyncSession,
    user_id: _uuid.UUID,
    vpc_id: str,
    min_perm: str = "read",
) -> VPC:
    """Get a VPC by ownership or group share."""
    vid = _uuid.UUID(vpc_id)
    result = await db.execute(
        select(VPC).where(VPC.id == vid, VPC.owner_id == user_id).options(selectinload(VPC.subnets))
    )
    vpc = result.scalar_one_or_none()
    if not vpc:
        res2 = await db.execute(select(VPC).where(VPC.id == vid).options(selectinload(VPC.subnets)))
        vpc = res2.scalar_one_or_none()
        if vpc and not await check_group_access(db, user_id, "vpc", vid, min_perm):
            vpc = None
    if not vpc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VPC not found")
    return vpc


# ---------------------------------------------------------------------------
# VPC CRUD
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[VPCRead])
async def list_vpcs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(VPC).where(VPC.owner_id == user.id).options(selectinload(VPC.subnets)).order_by(VPC.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/", response_model=VPCRead, status_code=status.HTTP_201_CREATED)
async def create_vpc(
    body: VPCCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    # Name uniqueness per user
    existing = await db.execute(select(VPC).where(VPC.owner_id == user.id, VPC.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="VPC name already exists")

    # Quota enforcement
    quota_row = await db.execute(select(UserQuota).where(UserQuota.user_id == user.id))
    quota = quota_row.scalar_one_or_none()
    if quota:
        count_row = await db.execute(select(func.count()).select_from(VPC).where(VPC.owner_id == user.id))
        vpc_count = count_row.scalar() or 0
        if vpc_count >= quota.max_networks:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"VPC quota exceeded (max {quota.max_networks})",
            )

    # Validate network mode
    if body.network_mode not in ("published", "private", "isolated"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid network mode. Must be one of: published, private, isolated",
        )

    # CIDR / gateway allocation
    cidr = body.cidr or await ipam_service.allocate_vpc_cidr(db)
    gateway = body.gateway or cidr_pool.get_gateway(cidr)

    # Enforce global CIDR uniqueness
    if not await ipam_service.check_cidr_globally_unique(db, cidr):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CIDR overlaps with an existing network. Each network must have a unique subnet.",
        )

    # Subnet size enforcement (tier-based)
    net = ipaddress.ip_network(cidr, strict=False)
    requested_prefix = net.prefixlen

    tier_row = await db.execute(select(UserTier).join(User, User.tier_id == UserTier.id).where(User.id == user.id))
    user_tier = tier_row.scalar_one_or_none()
    tier_max = user_tier.max_subnet_prefix if user_tier else None

    if tier_max is None:
        setting_row = await db.execute(
            select(SystemSetting).where(SystemSetting.key == "sdn.default_max_subnet_prefix")
        )
        setting = setting_row.scalar_one_or_none()
        max_prefix = int(setting.value) if setting else 24
    else:
        max_prefix = tier_max

    if requested_prefix < max_prefix:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Subnet too large. Your maximum allowed subnet size is /{max_prefix} "
                f"({2 ** (32 - max_prefix) - 2} hosts). Requested: /{requested_prefix}"
            ),
        )

    # VXLAN tag
    cluster_id = body.cluster_id if hasattr(body, "cluster_id") else "default"
    tag = sdn_service.allocate_vxlan_tag(cluster_id=cluster_id)

    # Persist VPC (flush to obtain id before generating vnet name)
    vpc = VPC(
        owner_id=user.id,
        name=body.name,
        cidr=cidr,
        gateway=gateway,
        dhcp_enabled=body.dhcp_enabled,
        network_mode=body.network_mode,
        vxlan_tag=tag,
        proxmox_zone="paws",
        status="creating",
        cluster_id=cluster_id,
    )
    db.add(vpc)
    await db.flush()

    # Proxmox VNet creation
    vnet_name = sdn_service.generate_vnet_name(str(vpc.id))
    vpc.proxmox_vnet = vnet_name
    try:
        sdn_service.create_vnet(vnet_name, tag, alias=body.name, cluster_id=cluster_id)
        vpc.status = "active"
    except Exception:
        logger.exception("Failed to create Proxmox VNet for VPC %s", vpc.id)
        vpc.status = "error"

    # Auto-create the single subnet for this network
    snat_enabled = body.snat_enabled
    proxmox_subnet_id = cidr.replace("/", "-")
    sub_status = "active"
    try:
        sdn_service.create_subnet(
            vnet_name,
            cidr,
            gateway,
            snat=snat_enabled,
            cluster_id=cluster_id,
        )
    except Exception:
        logger.exception("Failed to create Proxmox subnet %s on VNet %s", cidr, vnet_name)
        sub_status = "error"

    subnet = Subnet(
        vpc_id=vpc.id,
        name=body.name,
        cidr=cidr,
        gateway=gateway,
        is_public=False,
        snat_enabled=snat_enabled,
        dhcp_enabled=False,
        dns_server=body.dns_server,
        proxmox_subnet_id=proxmox_subnet_id,
        status=sub_status,
    )
    db.add(subnet)

    # Auto-create managed security group for published networks
    if body.network_mode == "published":
        sg = await _ensure_published_sg(db, user.id, body.name, cidr, cluster_id=cluster_id)
        vpc.security_group_id = sg.id

    await db.commit()

    await log_action(
        db,
        user.id,
        "vpc.create",
        resource_type="vpc",
        resource_id=vpc.id,
        details={"name": body.name, "cidr": cidr, "vxlan_tag": tag, "vnet": vnet_name},
    )

    result = await db.execute(select(VPC).where(VPC.id == vpc.id).options(selectinload(VPC.subnets)))
    return result.scalar_one()


@router.get("/{vpc_id}", response_model=VPCRead)
async def get_vpc(
    vpc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    return await _get_vpc(db, user.id, vpc_id)


@router.delete("/{vpc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vpc(
    vpc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vpc = await _get_vpc(db, user.id, vpc_id, min_perm="admin")

    if vpc.is_default:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete default VPC")

    # Reject if resources are still attached
    res = await db.execute(select(Resource).where(Resource.owner_id == user.id))
    for r in res.scalars().all():
        specs = r.specs
        if isinstance(specs, str):
            try:
                specs = json.loads(specs)
            except (json.JSONDecodeError, TypeError):
                specs = {}
        if isinstance(specs, dict) and specs.get("vpc_id") == vpc_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete VPC with attached resources",
            )

    # Remove Proxmox VNet (cascades to SDN subnets)
    if vpc.proxmox_vnet:
        try:
            sdn_service.delete_vnet(vpc.proxmox_vnet, cluster_id=vpc.cluster_id)
        except Exception:
            logger.exception("Failed to delete Proxmox VNet %s", vpc.proxmox_vnet)

    await log_action(
        db,
        user.id,
        "vpc.delete",
        resource_type="vpc",
        resource_id=vpc.id,
        details={"name": vpc.name},
    )

    await db.delete(vpc)
    await db.commit()


# ---------------------------------------------------------------------------
# Network Mode
# ---------------------------------------------------------------------------


class VPCModeUpdate(BaseModel):
    network_mode: str  # published, private, isolated


@router.put("/{vpc_id}/mode")
async def update_vpc_mode(
    vpc_id: str,
    body: VPCModeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Change the network mode for an entire VPC.

    All instances on this VPC will have their firewall rules re-applied
    to match the new mode.
    """
    from app.services.firewall_profile import FirewallProfileService

    if body.network_mode not in ("published", "private", "isolated"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid network mode. Must be one of: published, private, isolated",
        )

    vpc = await _get_vpc(db, user.id, vpc_id, min_perm="admin")

    if vpc.network_mode == body.network_mode:
        return {"status": "ok", "network_mode": vpc.network_mode, "updated_instances": 0}

    # Find all instances attached to this VPC
    all_resources = await db.execute(select(Resource).where(Resource.owner_id == user.id))
    attached = []
    for r in all_resources.scalars().all():
        specs = r.specs
        if isinstance(specs, str):
            try:
                specs = json.loads(specs)
            except (json.JSONDecodeError, TypeError):
                specs = {}
        if isinstance(specs, dict) and specs.get("vpc_id") == vpc_id:
            attached.append(r)

    # If changing to isolated or published, check no instance has this VPC as a secondary NIC
    if body.network_mode in ("published", "isolated"):
        for r in attached:
            specs = r.specs if isinstance(r.specs, dict) else json.loads(r.specs or "{}")
            secondary_vpcs = specs.get("secondary_vpc_ids", [])
            if secondary_vpcs:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot change to {body.network_mode} mode: instance "
                        f"'{r.display_name}' has secondary NICs attached. "
                        "Remove secondary NICs first."
                    ),
                )

    # Check if any OTHER instance has a secondary NIC pointing to this VPC
    if body.network_mode in ("published", "isolated"):
        other_resources = await db.execute(select(Resource).where(Resource.owner_id == user.id))
        for r in other_resources.scalars().all():
            specs = r.specs if isinstance(r.specs, dict) else json.loads(r.specs or "{}")
            secondary_vpc_ids = specs.get("secondary_vpc_ids", [])
            if vpc_id in secondary_vpc_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot change to {body.network_mode} mode: instance "
                        f"'{r.display_name}' has a secondary NIC on this network. "
                        "Remove secondary NICs first."
                    ),
                )

    # Update VPC mode
    vpc.network_mode = body.network_mode

    # Manage security group for published mode
    if body.network_mode == "published" and not vpc.security_group_id:
        sg = await _ensure_published_sg(db, user.id, vpc.name, vpc.cidr, cluster_id=vpc.cluster_id)
        vpc.security_group_id = sg.id
    elif body.network_mode != "published" and vpc.security_group_id:
        # Unlink (but keep the SG so rules are preserved if user switches back)
        vpc.security_group_id = None

    # Load settings for firewall rules
    lan_ranges = await FirewallProfileService.get_lan_ranges_async(db)
    upstream_ips = await FirewallProfileService.get_upstream_ips_async(db)

    # Re-apply firewall rules on all attached instances
    updated = 0
    errors = []
    for r in attached:
        r.network_mode = body.network_mode
        specs = r.specs if isinstance(r.specs, dict) else json.loads(r.specs or "{}")
        subnet_cidr = specs.get("subnet_cidr", vpc.cidr)

        try:
            vmtype = "lxc" if r.resource_type == "lxc" else "qemu"
            FirewallProfileService.enable_firewall(r.proxmox_node, r.proxmox_vmid, vmtype)
            FirewallProfileService.apply_network_mode(
                r.proxmox_node,
                r.proxmox_vmid,
                vmtype,
                body.network_mode,
                subnet_cidr,
                lan_ranges=lan_ranges,
                upstream_ips=upstream_ips,
            )
            updated += 1
        except Exception as exc:
            logger.warning(
                "Failed to apply firewall for %s on %s/%s: %s",
                body.network_mode,
                r.proxmox_node,
                r.proxmox_vmid,
                exc,
            )
            errors.append(str(r.display_name))

        # Auto-attach/detach managed SG to instances
        if body.network_mode == "published" and vpc.security_group_id:
            existing_link = await db.execute(
                select(ResourceSecurityGroup).where(
                    ResourceSecurityGroup.resource_id == r.id,
                    ResourceSecurityGroup.security_group_id == vpc.security_group_id,
                )
            )
            if not existing_link.scalar_one_or_none():
                db.add(
                    ResourceSecurityGroup(
                        resource_id=r.id,
                        security_group_id=vpc.security_group_id,
                    )
                )
        elif body.network_mode != "published" and vpc.security_group_id is None:
            # Detach any previously auto-linked published SGs from prior mode
            pass  # SG was unlinked from VPC, but ResourceSecurityGroup persists for safety

    await db.commit()

    await log_action(
        db,
        user.id,
        "vpc.mode_change",
        resource_type="vpc",
        resource_id=vpc.id,
        details={
            "name": vpc.name,
            "network_mode": body.network_mode,
            "updated_instances": updated,
        },
    )

    result = {"status": "ok", "network_mode": body.network_mode, "updated_instances": updated}
    if errors:
        result["warnings"] = f"Failed to update firewall on: {', '.join(errors)}"
    return result


# ---------------------------------------------------------------------------
# Instances attached to VPC
# ---------------------------------------------------------------------------


@router.get("/{vpc_id}/instances")
async def list_vpc_instances(
    vpc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List resources attached to a VPC with allocated and live IP addresses."""
    vpc_result = await db.execute(select(VPC).where(VPC.id == _uuid.UUID(vpc_id), VPC.owner_id == user.id))
    if not vpc_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VPC not found")

    result = await db.execute(select(Resource).where(Resource.owner_id == user.id))

    # Pre-load all IP reservations for this VPC's subnets
    subnet_result = await db.execute(select(Subnet).where(Subnet.vpc_id == _uuid.UUID(vpc_id)))
    subnet_ids = [s.id for s in subnet_result.scalars().all()]
    reservations_by_resource: dict[str, list[str]] = {}
    if subnet_ids:
        res_result = await db.execute(select(IPReservation).where(IPReservation.subnet_id.in_(subnet_ids)))
        for res in res_result.scalars().all():
            if res.resource_id:
                rid = str(res.resource_id)
                reservations_by_resource.setdefault(rid, []).append(res.ip_address)

    instances = []
    for r in result.scalars().all():
        specs = r.specs
        if isinstance(specs, str):
            try:
                specs = json.loads(specs)
            except (json.JSONDecodeError, TypeError):
                specs = {}
        if isinstance(specs, dict) and specs.get("vpc_id") == vpc_id:
            rid = str(r.id)
            allocated_ips = reservations_by_resource.get(rid, [])

            # Get live IPs from guest agent (QEMU) or LXC net config
            live_ips: list[str] = []
            if r.proxmox_node and r.proxmox_vmid:
                try:
                    if r.resource_type == "qemu":
                        ifaces = get_pve(r.cluster_id).get_agent_network_interfaces(r.proxmox_node, r.proxmox_vmid)
                        for iface in ifaces:
                            for addr in iface.get("ip-addresses", []):
                                ip = addr.get("ip-address", "")
                                if addr.get("ip-address-type") == "ipv4" and not ip.startswith("127."):
                                    live_ips.append(ip)
                    elif r.resource_type == "lxc":
                        config = get_pve(r.cluster_id).get_container_config(r.proxmox_node, r.proxmox_vmid)
                        for key, val in config.items():
                            if key.startswith("net") and key[3:].isdigit() and isinstance(val, str):
                                for part in val.split(","):
                                    if part.startswith("ip=") and part != "ip=dhcp":
                                        ip_cidr = part[3:]
                                        live_ips.append(ip_cidr.split("/")[0])
                except Exception:
                    pass

            inst_data: dict[str, Any] = {
                "id": rid,
                "name": r.display_name,
                "type": r.resource_type,
                "status": r.status,
                "proxmox_node": r.proxmox_node,
                "proxmox_vmid": r.proxmox_vmid,
                "allocated_ips": allocated_ips,
                "live_ips": live_ips,
                "ip_addresses": allocated_ips or live_ips,
            }
            instances.append(inst_data)
    return instances


# ---------------------------------------------------------------------------
# Instance IP management within VPC
# ---------------------------------------------------------------------------


class IPChangeRequest(BaseModel):
    new_ip: str


@router.put("/{vpc_id}/instances/{resource_id}/ip")
async def change_instance_ip(
    vpc_id: str,
    resource_id: str,
    body: IPChangeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Change the static IP of an instance within its network's subnet range."""
    vpc_result = await db.execute(select(VPC).where(VPC.id == _uuid.UUID(vpc_id), VPC.owner_id == user.id))
    vpc = vpc_result.scalar_one_or_none()
    if not vpc:
        raise HTTPException(status_code=404, detail="VPC not found")

    resource_result = await db.execute(
        select(Resource).where(Resource.id == _uuid.UUID(resource_id), Resource.owner_id == user.id)
    )
    resource = resource_result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Instance not found")

    specs = resource.specs
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except (json.JSONDecodeError, TypeError):
            specs = {}
    if not isinstance(specs, dict) or specs.get("vpc_id") != vpc_id:
        raise HTTPException(status_code=400, detail="Instance is not attached to this VPC")

    # Find the subnet the new IP belongs to
    new_ip_obj = ipaddress.ip_address(body.new_ip)
    subnet_result = await db.execute(
        select(Subnet)
        .where(Subnet.vpc_id == vpc.id, Subnet.status == "active")
        .options(selectinload(Subnet.ip_reservations))
    )
    target_subnet = None
    for subnet in subnet_result.scalars().all():
        network = ipaddress.ip_network(subnet.cidr, strict=False)
        if new_ip_obj in network:
            target_subnet = subnet
            break

    if not target_subnet:
        raise HTTPException(status_code=400, detail="IP address is not within any active subnet")

    network = ipaddress.ip_network(target_subnet.cidr, strict=False)
    gateway = target_subnet.gateway or str(list(network.hosts())[0])
    if body.new_ip == gateway:
        raise HTTPException(status_code=400, detail="Cannot assign the gateway IP")
    if new_ip_obj == network.network_address or new_ip_obj == network.broadcast_address:
        raise HTTPException(status_code=400, detail="Cannot use network or broadcast address")

    # Check if IP is already taken by another resource
    used = {r.ip_address for r in target_subnet.ip_reservations if str(r.resource_id) != resource_id}
    if body.new_ip in used:
        raise HTTPException(status_code=409, detail="IP address already in use")

    # Release old reservations for this resource in any subnet of this VPC
    vpc_subnet_ids_result = await db.execute(select(Subnet.id).where(Subnet.vpc_id == vpc.id))
    vpc_subnet_ids = [s for s in vpc_subnet_ids_result.scalars().all()]
    if vpc_subnet_ids:
        from sqlalchemy import delete as sa_delete

        await db.execute(
            sa_delete(IPReservation).where(
                IPReservation.resource_id == resource.id,
                IPReservation.subnet_id.in_(vpc_subnet_ids),
            )
        )

    # Create new reservation
    db.add(
        IPReservation(
            subnet_id=target_subnet.id,
            ip_address=body.new_ip,
            resource_id=resource.id,
            label=resource.display_name,
            is_gateway=False,
            owner_id=user.id,
            cluster_id=vpc.cluster_id,
        )
    )

    # Apply to Proxmox via unified helpers from compute module
    prefix_len = network.prefixlen
    dns_server = target_subnet.dns_server or "1.1.1.1"
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
    try:
        from app.routers.compute import _apply_nic, _build_net0

        net0_val = _build_net0(
            vmtype,
            vpc.proxmox_vnet,
            ip=body.new_ip,
            prefix_len=prefix_len,
            gateway=gateway,
        )
        _apply_nic(
            resource.proxmox_node,
            resource.proxmox_vmid,
            vmtype,
            net0_val,
            ip=body.new_ip,
            prefix_len=prefix_len,
            gateway=gateway,
            dns_server=dns_server,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to apply IP change: {e}")

    await db.commit()
    await log_action(db, user.id, "ip_change", resource_id=str(resource.id), details=f"IP changed to {body.new_ip}")
    return {"status": "ok", "ip_address": body.new_ip, "subnet": target_subnet.cidr}

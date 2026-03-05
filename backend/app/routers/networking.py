"""SDN / networking management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import User
from app.services.audit_service import log_action
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/networking", tags=["networking"])


class VNetCreateRequest(BaseModel):
    name: str
    zone: str
    tag: int | None = None  # VLAN tag or VxLAN VNI
    alias: str | None = None


class FirewallRuleRequest(BaseModel):
    direction: str = "in"  # in, out
    action: str = "ACCEPT"  # ACCEPT, DROP, REJECT
    proto: str | None = None  # tcp, udp, icmp
    dport: str | None = None  # destination port(s)
    sport: str | None = None  # source port(s)
    source: str | None = None  # source IP/CIDR
    dest: str | None = None  # destination IP/CIDR
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


@router.get("/vms/{node}/{vmid}/firewall")
async def get_firewall_rules(
    node: str,
    vmid: int,
    _: User = Depends(get_current_active_user),
):
    try:
        return proxmox_client.api.nodes(node).qemu(vmid).firewall.rules.get()
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
            "type": "group" if body.direction == "group" else body.direction,
            "action": body.action,
            "enable": body.enable,
        }
        for field in ("proto", "dport", "sport", "source", "dest", "comment"):
            val = getattr(body, field)
            if val is not None:
                params[field] = val

        proxmox_client.api.nodes(node).qemu(vmid).firewall.rules.post(**params)
        await log_action(db, user.id, "firewall_add", "vm", details={"vmid": vmid, "rule": params})
        return {"status": "created"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Static IP Management ------------------------------------------------

# In-memory IP reservations (per-VPC). Production would use DB.
_ip_reservations: dict[str, dict[str, dict]] = {}  # vpc_id -> {ip -> {user_id, resource_id, ...}}


class StaticIPRequest(BaseModel):
    subnet_cidr: str
    ip_address: str | None = None  # auto-assign if None
    resource_id: str | None = None
    label: str | None = None


@router.post("/vpcs/{vpc_id}/ips")
async def reserve_static_ip(
    vpc_id: str,
    body: StaticIPRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Reserve a static IP address within a VPC subnet."""
    import ipaddress

    try:
        network = ipaddress.ip_network(body.subnet_cidr, strict=False)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid subnet CIDR")

    vpc_ips = _ip_reservations.setdefault(vpc_id, {})

    if body.ip_address:
        ip = body.ip_address
        if ip in vpc_ips:
            raise HTTPException(status_code=409, detail="IP already reserved")
        if ipaddress.ip_address(ip) not in network:
            raise HTTPException(status_code=400, detail="IP not in subnet range")
    else:
        # Auto-assign: skip network, gateway (.1), and broadcast
        for host in list(network.hosts())[1:]:
            if str(host) not in vpc_ips:
                ip = str(host)
                break
        else:
            raise HTTPException(status_code=409, detail="No available IPs in subnet")

    reservation = {
        "ip": ip,
        "vpc_id": vpc_id,
        "subnet_cidr": body.subnet_cidr,
        "user_id": str(user.id),
        "resource_id": body.resource_id,
        "label": body.label,
    }
    vpc_ips[ip] = reservation
    await log_action(db, user.id, "ip_reserve", "network", details={"ip": ip, "vpc_id": vpc_id})
    return reservation


@router.get("/vpcs/{vpc_id}/ips")
async def list_static_ips(
    vpc_id: str,
    user: User = Depends(get_current_active_user),
):
    """List reserved static IPs in a VPC."""
    vpc_ips = _ip_reservations.get(vpc_id, {})
    user_ips = [v for v in vpc_ips.values() if v["user_id"] == str(user.id)]
    return user_ips


@router.delete("/vpcs/{vpc_id}/ips/{ip}")
async def release_static_ip(
    vpc_id: str,
    ip: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Release a reserved static IP."""
    vpc_ips = _ip_reservations.get(vpc_id, {})
    reservation = vpc_ips.get(ip)
    if not reservation or reservation["user_id"] != str(user.id):
        raise HTTPException(status_code=404, detail="IP reservation not found")
    del vpc_ips[ip]
    await log_action(db, user.id, "ip_release", "network", details={"ip": ip, "vpc_id": vpc_id})
    return {"status": "released", "ip": ip}

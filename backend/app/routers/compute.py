"""VM and container provisioning, lifecycle, and management endpoints."""

import asyncio
import json
import logging
import ssl
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.core.lifecycle import get_action_transition, validate_instance_specs
from app.models.models import Resource, SSHKeyPair, Subnet, SystemSetting, User, UserQuota, VPC, VMIDPool, Volume
from app.services.audit_service import log_action
from app.services.firewall_profile import FirewallProfileService
from app.services.node_service import get_next_vmid, select_node
from app.services.proxmox_client import proxmox_client
from app.services.pbs_client import pbs_client
from app.services.pool_service import ensure_user_pool, add_resource_to_pool, cleanup_user_pool

logger = logging.getLogger(__name__)
from app.services.rate_limiter import check_action_rate_limit

router = APIRouter(prefix="/api/compute", tags=["compute"])


# --- Schemas ---


class VMCreateRequest(BaseModel):
    name: str
    template_vmid: int
    cores: int = 2
    memory_mb: int = 2048
    disk_gb: int = 32
    storage: str = "local-lvm"
    instance_type: str | None = None
    ssh_key_ids: list[str] | None = None
    security_group_ids: list[str] | None = None
    placement_strategy: str | None = None
    termination_protected: bool = False
    # Instance configuration
    hostname: str | None = None
    ci_user: str | None = None
    ci_password: str | None = None
    dns_server: str | None = None
    dns_domain: str | None = None
    ssh_keys: list[str] | None = None  # direct public keys (fallback, prefer ssh_key_ids)
    nameservers: list[str] | None = None  # legacy
    searchdomains: list[str] | None = None  # legacy
    vpc_id: str | None = None
    network_mode: str = "private"


class ContainerCreateRequest(BaseModel):
    name: str
    template: str | None = None
    template_vmid: int | None = None
    cores: int = 1
    memory_mb: int = 1024
    disk_gb: int = 16
    storage: str = "local-lvm"
    ssh_key_ids: list[str] | None = None
    security_group_ids: list[str] | None = None
    termination_protected: bool = False
    hostname: str | None = None
    ci_password: str | None = None
    dns_server: str | None = None
    dns_domain: str | None = None
    vpc_id: str | None = None
    network_mode: str = "private"


class VMActionRequest(BaseModel):
    action: str  # start, stop, shutdown, reboot, suspend, resume, terminate
    force: bool = False  # force stop vs graceful shutdown


class SnapshotRequest(BaseModel):
    name: str
    description: str = ""


class TerminationProtectionRequest(BaseModel):
    enabled: bool


class InstanceResizeRequest(BaseModel):
    cores: int | None = None
    memory_mb: int | None = None


# --- VM Endpoints ---


# --- Unified config helpers ---
# All instance configuration (cloud-init for VMs, container config for LXC)
# MUST go through these helpers. Do NOT call proxmox_client.update_vm_config
# or set_container_config with config params (ciuser, sshkeys, nameserver, etc.)
# directly from endpoint code. This ensures a single code path for config
# application, making it testable and consistent across create and update flows.


async def _resolve_ssh_keys(
    db: AsyncSession, user_id: uuid.UUID, ssh_key_ids: list[str] | None,
) -> list[str]:
    """Resolve SSH key IDs to actual public key strings from the database."""
    if not ssh_key_ids:
        return []
    result = await db.execute(
        select(SSHKeyPair).where(
            SSHKeyPair.id.in_([uuid.UUID(kid) for kid in ssh_key_ids]),
            SSHKeyPair.owner_id == user_id,
        )
    )
    return [k.public_key for k in result.scalars().all()]


def _apply_instance_config(
    node: str,
    vmid: int,
    resource_type: str,
    *,
    username: str | None = None,
    password: str | None = None,
    hostname: str | None = None,
    dns_server: str | None = None,
    dns_domain: str | None = None,
    ssh_public_keys: list[str] | None = None,
) -> None:
    """Apply instance configuration to Proxmox (cloud-init for VMs, config for LXC).

    This is the SINGLE code path for all config application. Both create_vm,
    create_container, and update_instance_config call this function.

    Args:
        node: Proxmox node name
        vmid: VM/container ID
        resource_type: "qemu", "vm", or "lxc"
        username: Cloud-init user (VM) - ignored for LXC
        password: Cloud-init password (VM) or container root password (LXC)
        hostname: VM name / container hostname
        dns_server: DNS nameserver(s)
        dns_domain: DNS search domain
        ssh_public_keys: List of raw public key strings (already resolved from IDs)
    """
    import urllib.parse

    is_lxc = resource_type == "lxc"

    if is_lxc:
        params: dict[str, str] = {}
        if hostname is not None:
            params["hostname"] = hostname
        if dns_server is not None:
            params["nameserver"] = dns_server
        if dns_domain is not None:
            params["searchdomain"] = dns_domain
        if ssh_public_keys is not None:
            params["ssh-public-keys"] = "\n".join(ssh_public_keys) + "\n" if ssh_public_keys else ""
        if params:
            proxmox_client.set_container_config(node, vmid, **params)
        # LXC password must be set in a separate API call
        if password is not None:
            proxmox_client.set_container_config(node, vmid, password=password)
    else:
        params = {}
        if username is not None:
            params["ciuser"] = username
        if password is not None:
            params["cipassword"] = password
        if hostname is not None:
            params["name"] = hostname
        if dns_server is not None:
            params["nameserver"] = dns_server
        if dns_domain is not None:
            params["searchdomain"] = dns_domain
        if ssh_public_keys is not None:
            params["sshkeys"] = urllib.parse.quote(
                "\n".join(ssh_public_keys) + "\n", safe=""
            ) if ssh_public_keys else ""
        if params:
            proxmox_client.update_vm_config(node, vmid, **params)
            proxmox_client.regenerate_cloudinit(node, vmid)


def _build_net0(
    resource_type: str,
    bridge: str,
    *,
    ip: str | None = None,
    prefix_len: int | None = None,
    gateway: str | None = None,
    firewall: int = 1,
    rate: float = 0,
    link_down: bool = False,
    model: str = "virtio",
    iface_name: str | None = None,
) -> str:
    """Build a net0 config string for Proxmox. SINGLE source of truth for NIC config format.

    All net0/NIC config building MUST go through this function to avoid
    format inconsistencies between create, update, and IP change paths.
    """
    if resource_type == "lxc":
        name = iface_name or "eth0"
        parts = [f"name={name},bridge={bridge}"]
        if ip and prefix_len and gateway:
            parts.append(f"ip={ip}/{prefix_len},gw={gateway}")
        parts.append(f"firewall={firewall}")
    else:
        parts = [f"{model},bridge={bridge}"]
        parts.append(f"firewall={firewall}")
    if link_down:
        parts.append("link_down=1")
    if rate > 0:
        parts.append(f"rate={rate}")
    return ",".join(parts)


def _apply_nic(
    node: str,
    vmid: int,
    resource_type: str,
    net0_val: str,
    *,
    ip: str | None = None,
    prefix_len: int | None = None,
    gateway: str | None = None,
    dns_server: str | None = None,
) -> None:
    """Apply a NIC config to Proxmox. For VMs, also sets cloud-init ipconfig0.

    All NIC application MUST go through this function so that VM ipconfig0
    and LXC net0 IP embedding stay consistent.
    """
    if resource_type == "lxc":
        proxmox_client.set_container_config(node, vmid, net0=net0_val)
    else:
        proxmox_client.update_vm_config(node, vmid, net0=net0_val, agent="1")
        # VMs use cloud-init ipconfig0 for static IP (LXC embeds IP in net0)
        if ip and prefix_len and gateway:
            ci_ip_params: dict[str, str] = {
                "ipconfig0": f"ip={ip}/{prefix_len},gw={gateway}",
            }
            if dns_server:
                ci_ip_params["nameserver"] = dns_server
            proxmox_client.update_vm_config(node, vmid, **ci_ip_params)
        proxmox_client.regenerate_cloudinit(node, vmid)


def _apply_paws_metadata(
    node: str,
    vmid: int,
    vmtype: str,
    user: User,
    resource: Resource,
) -> None:
    """Stamp PAWS ownership tags and description on a Proxmox VM/container."""
    tags = "paws-managed"
    description = (
        f"PAWS Managed Resource\n\n"
        f"Owner: {user.username} ({user.email or 'N/A'})\n\n"
        f"User ID: {user.id}\n\n"
        f"Resource ID: {resource.id}\n\n"
        f"Name: {resource.display_name}\n\n"
        f"Created: {resource.created_at or 'N/A'}\n\n"
        f"---\n\n"
        f"This instance is managed by PAWS. Do not modify tags or description manually."
    )
    try:
        if vmtype == "lxc":
            proxmox_client.set_container_config(node, vmid, tags=tags, description=description)
        else:
            proxmox_client.update_vm_config(node, vmid, tags=tags, description=description)
        logger.info("Applied PAWS metadata to VMID %s on %s (type=%s)", vmid, node, vmtype)
    except Exception as e:
        logger.warning("Failed to apply PAWS metadata to VMID %s on %s: %s", vmid, node, e)


@router.post("/vms", status_code=status.HTTP_202_ACCEPTED)
async def create_vm(
    body: VMCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    # Rate limit
    allowed, _ = await check_action_rate_limit(str(user.id), "vm_create", 30)
    if not allowed:
        raise HTTPException(status_code=429, detail="VM creation rate limit exceeded (max 30/hour)")

    # Spec validation
    spec_errors = validate_instance_specs(body.cores, body.memory_mb, body.disk_gb)
    if spec_errors:
        raise HTTPException(status_code=422, detail=[{"field": e.field, "message": e.message} for e in spec_errors])

    # Quota check
    quota = await _get_quota(db, user.id)
    vm_count = await _count_resources(db, user.id, "vm")
    if vm_count >= quota.max_vms:
        raise HTTPException(status_code=403, detail=f"VM quota exceeded ({quota.max_vms} max)")
    if body.cores > quota.max_vcpus:
        raise HTTPException(status_code=403, detail=f"vCPU quota exceeded ({quota.max_vcpus} max)")

    # Get next VMID using configured range - check both pool and resources table
    pool_vmids = set((await db.execute(select(VMIDPool.vmid))).scalars().all())
    resource_vmids = set(
        (await db.execute(select(Resource.proxmox_vmid).where(Resource.proxmox_vmid.isnot(None)))).scalars().all()
    )
    existing = pool_vmids | resource_vmids
    vmid_start, vmid_end = await _get_vmid_range(db)
    new_vmid = get_next_vmid(existing, start=vmid_start, end=vmid_end)

    # Select node
    strategy = body.placement_strategy or "least-loaded"
    try:
        node = select_node(strategy)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Reserve VMID first (without creating resource yet)
    db.add(VMIDPool(vmid=new_vmid, resource_id=None))
    await db.commit()

    # Find template's source node and determine clone strategy
    try:
        template_node = proxmox_client.find_vm_node(body.template_vmid)
        if not template_node:
            raise RuntimeError(f"Template VMID {body.template_vmid} not found on any node")

        template_type = proxmox_client.get_resource_type(body.template_vmid) or "qemu"
        is_lxc_template = template_type == "lxc"

        if is_lxc_template:
            template_disk_storage = proxmox_client.get_container_disk_storage(template_node, body.template_vmid)
        else:
            template_disk_storage = proxmox_client.get_vm_disk_storage(template_node, body.template_vmid)
        storage_is_shared = (
            proxmox_client.is_storage_shared(template_disk_storage) if template_disk_storage else False
        )

        # Linked clone if storage is shared, full clone if local
        use_full_clone = not storage_is_shared
        needs_migration = template_node != node

        # Clone on the template's source node
        if is_lxc_template:
            upid = proxmox_client.clone_container(
                node=template_node,
                source_vmid=body.template_vmid,
                new_vmid=new_vmid,
                hostname=body.name,
                full=int(use_full_clone),
                target=template_node,
                storage=body.storage if use_full_clone else None,
            )
            resource_type = "lxc"
        else:
            upid = proxmox_client.clone_vm(
                node=template_node,
                source_vmid=body.template_vmid,
                new_vmid=new_vmid,
                name=body.name,
                full=int(use_full_clone),
                target=template_node,
                storage=body.storage if use_full_clone else None,
            )
            resource_type = "vm"
    except Exception as e:
        # Clone failed - release VMID
        result = await db.execute(select(VMIDPool).where(VMIDPool.vmid == new_vmid))
        vmid_entry = result.scalar_one_or_none()
        if vmid_entry:
            await db.delete(vmid_entry)
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Failed to clone template: {e}")

    # Clone started - create the resource record on the clone node for now
    clone_node = template_node  # Clone lives on source node initially
    resource = Resource(
        owner_id=user.id,
        resource_type=resource_type,
        display_name=body.name,
        proxmox_vmid=new_vmid,
        proxmox_node=clone_node,
        status="provisioning",
        termination_protected=body.termination_protected,
        specs=json.dumps({
            "cores": body.cores, "memory_mb": body.memory_mb, "disk_gb": body.disk_gb,
            "hostname": body.hostname, "vpc_id": body.vpc_id,
        }),
    )
    db.add(resource)

    # Update VMID pool entry with resource reference
    vmid_result = await db.execute(select(VMIDPool).where(VMIDPool.vmid == new_vmid))
    vmid_entry = vmid_result.scalar_one_or_none()
    if vmid_entry:
        vmid_entry.resource_id = resource.id

    await db.commit()

    # Assign to Proxmox pool for cluster-side management
    try:
        await ensure_user_pool(db, user)
        await add_resource_to_pool(db, user, new_vmid)
    except Exception:
        pass  # Best-effort pool assignment

    # Wait for clone to complete, then migrate if needed
    try:
        proxmox_client.wait_for_task(clone_node, upid, timeout=120)
    except Exception as wait_err:
        logger.warning("Clone task wait failed for VMID %s: %s", new_vmid, wait_err)

    if needs_migration:
        try:
            if is_lxc_template:
                mig_upid = proxmox_client.migrate_container(clone_node, new_vmid, target=node, online=False)
            else:
                mig_upid = proxmox_client.migrate_vm(clone_node, new_vmid, target=node, online=False)
            # Wait for migration to finish before applying config
            proxmox_client.wait_for_task(clone_node, mig_upid, timeout=300)
            resource.proxmox_node = node
            await db.commit()
        except Exception as mig_err:
            logger.warning("Migration of VMID %s to %s failed: %s", new_vmid, node, mig_err)
            # VM stays on clone_node; update resource to reflect reality
            actual_node = proxmox_client.find_vm_node(new_vmid) or clone_node
            if resource.proxmox_node != actual_node:
                resource.proxmox_node = actual_node
                await db.commit()

    # Resolve SSH keys and apply instance configuration
    resolved_ssh_keys = await _resolve_ssh_keys(db, user.id, body.ssh_key_ids)
    if body.ssh_keys:
        resolved_ssh_keys.extend(body.ssh_keys)

    rtype = "lxc" if is_lxc_template else "qemu"
    try:
        # Resize specs (cores/memory) - separate from config
        if is_lxc_template:
            proxmox_client.set_container_config(
                resource.proxmox_node, new_vmid,
                cores=body.cores, memory=body.memory_mb,
            )
        else:
            proxmox_client.update_vm_config(
                resource.proxmox_node, new_vmid,
                cores=body.cores, memory=body.memory_mb,
            )
        # Apply instance config via unified helper
        _apply_instance_config(
            resource.proxmox_node, new_vmid, rtype,
            username=body.ci_user or ("paws" if not is_lxc_template else None),
            password=body.ci_password,
            hostname=body.hostname,
            dns_server=body.dns_server or (
                " ".join(body.nameservers) if body.nameservers else None
            ),
            dns_domain=body.dns_domain or (
                ",".join(body.searchdomains) if body.searchdomains else None
            ),
            ssh_public_keys=resolved_ssh_keys if resolved_ssh_keys else None,
        )
    except Exception as cfg_err:
        logger.error("Failed to apply instance config for VMID %s: %s", new_vmid, cfg_err, exc_info=True)

    # Stamp PAWS ownership tags and notes on the Proxmox resource
    _apply_paws_metadata(resource.proxmox_node, new_vmid, resource_type, user, resource)

    # Apply VPC networking (NIC bridge, bandwidth, firewall mode)
    await _resolve_vpc_networking(db, user, resource, body.vpc_id, body.network_mode)
    await db.commit()

    await log_action(db, user.id, f"{resource_type}_create", resource_type, resource.id, {"vmid": new_vmid, "node": resource.proxmox_node})
    return {"id": str(resource.id), "vmid": new_vmid, "node": resource.proxmox_node, "status": "provisioning", "task": upid, "type": resource_type}


@router.get("/vms")
async def list_vms(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    status_filter: str | None = None,
    name_filter: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    include_destroyed: bool = False,
):
    query = select(Resource).where(Resource.owner_id == user.id, Resource.resource_type == "vm")

    if not include_destroyed:
        query = query.where(Resource.status.notin_(["destroyed", "error", "creating"]))
    if status_filter:
        query = query.where(Resource.status == status_filter)
    if name_filter:
        query = query.where(Resource.display_name.ilike(f"%{name_filter}%"))

    sort_col = getattr(Resource, sort_by, Resource.created_at)
    query = query.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    result = await db.execute(query)
    resources = result.scalars().all()
    vms = []
    for r in resources:
        vm_data = {
            "id": str(r.id),
            "name": r.display_name,
            "resource_type": r.resource_type,
            "vmid": r.proxmox_vmid,
            "node": r.proxmox_node,
            "status": r.status,
            "specs": json.loads(r.specs) if r.specs else {},
            "termination_protected": r.termination_protected,
            "tags": json.loads(r.tags) if r.tags else [],
            "created_at": str(r.created_at),
            "last_accessed_at": r.last_accessed_at.isoformat() if r.last_accessed_at else None,
        }
        # Fetch live status if running
        if r.status not in ("destroyed", "error", "creating") and r.proxmox_vmid and r.proxmox_node:
            try:
                live = _get_live_status(r)
                vm_data["live_status"] = live.get("status")
                vm_data["cpu_usage"] = live.get("cpu", 0)
                vm_data["mem_usage"] = live.get("mem", 0)
                vm_data["uptime"] = live.get("uptime", 0)
                vm_data["netin"] = live.get("netin", 0)
                vm_data["netout"] = live.get("netout", 0)
            except Exception:
                vm_data["live_status"] = "unknown"
        vms.append(vm_data)
    return vms


@router.get("/vms/{resource_id}")
async def get_vm(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get a single VM by resource ID with live status from Proxmox."""
    r = await _get_user_resource(db, user.id, resource_id, "vm")
    vm_data = {
        "id": str(r.id),
        "display_name": r.display_name,
        "resource_type": r.resource_type,
        "proxmox_vmid": r.proxmox_vmid,
        "proxmox_node": r.proxmox_node,
        "status": r.status,
        "specs": json.loads(r.specs) if r.specs else {},
        "termination_protected": r.termination_protected,
        "tags": json.loads(r.tags) if r.tags else [],
        "created_at": str(r.created_at),
        "last_accessed_at": r.last_accessed_at.isoformat() if r.last_accessed_at else None,
    }
    if r.status not in ("destroyed", "error", "creating") and r.proxmox_vmid and r.proxmox_node:
        try:
            live = _get_live_status(r)
            vm_data["live_status"] = live.get("status")
            vm_data["cpu_usage"] = live.get("cpu", 0)
            vm_data["mem_usage"] = live.get("mem", 0)
            vm_data["uptime"] = live.get("uptime", 0)
            vm_data["netin"] = live.get("netin", 0)
            vm_data["netout"] = live.get("netout", 0)
        except Exception:
            # Node might be wrong - try to find the correct one
            actual_node = proxmox_client.find_vm_node(r.proxmox_vmid)
            if actual_node and actual_node != r.proxmox_node:
                r.proxmox_node = actual_node
                await db.commit()
                vm_data["proxmox_node"] = actual_node
                try:
                    live = _get_live_status(r)
                    vm_data["live_status"] = live.get("status")
                    vm_data["cpu_usage"] = live.get("cpu", 0)
                    vm_data["mem_usage"] = live.get("mem", 0)
                    vm_data["uptime"] = live.get("uptime", 0)
                    vm_data["netin"] = live.get("netin", 0)
                    vm_data["netout"] = live.get("netout", 0)
                except Exception:
                    vm_data["live_status"] = "unknown"
            else:
                vm_data["live_status"] = "unknown"
    return vm_data


@router.post("/vms/{resource_id}/action")
async def vm_action(
    resource_id: str,
    body: VMActionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="operate")
    node, vmid = resource.proxmox_node, resource.proxmox_vmid
    rtype = resource.resource_type

    if body.action == "terminate":
        if resource.termination_protected:
            raise HTTPException(status_code=403, detail="Termination protection is enabled")
        return await _terminate_vm(db, user, resource)

    if body.action == "suspend" and rtype == "vm":
        try:
            upid = proxmox_client.suspend_vm(node, vmid, to_disk=False)
            await log_action(db, user.id, "vm_suspend", rtype, resource.id)
            return {"status": "ok", "task": upid}
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))
    elif body.action == "hibernate" and rtype == "vm":
        try:
            upid = proxmox_client.suspend_vm(node, vmid, to_disk=True)
            await log_action(db, user.id, "vm_hibernate", rtype, resource.id)
            return {"status": "ok", "task": upid}
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    # "stop" always means immediate/force stop; "shutdown" is graceful
    action = body.action

    try:
        upid = _do_action(resource, action)
        await log_action(db, user.id, f"{rtype}_{body.action}", rtype, resource.id)
        return {"status": "ok", "task": upid}
    except ValueError as e:
        code = 403 if "Network safety" in str(e) else 400
        raise HTTPException(status_code=code, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/vms/{resource_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_vm(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")
    if resource.termination_protected:
        raise HTTPException(status_code=403, detail="Termination protection is enabled. Disable it first.")
    return await _terminate_vm(db, user, resource)


@router.post("/vms/{resource_id}/keepalive")
async def keepalive_vm(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Touch last_accessed_at to prevent idle lifecycle enforcement."""
    r = await _get_user_resource(db, user.id, resource_id, "vm")
    return {"last_accessed_at": r.last_accessed_at.isoformat() if r.last_accessed_at else None}


@router.patch("/vms/{resource_id}/termination-protection")
async def set_vm_termination_protection(
    resource_id: str,
    body: TerminationProtectionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")
    resource.termination_protected = body.enabled
    await db.commit()
    return {"termination_protected": body.enabled}


@router.patch("/vms/{resource_id}/resize")
async def resize_vm(
    resource_id: str,
    body: InstanceResizeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Resize CPU/RAM on a stopped VM."""
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")
    if resource.status not in ("stopped", "creating"):
        raise HTTPException(status_code=409, detail="VM must be stopped to resize")

    specs = json.loads(resource.specs) if resource.specs else {}
    new_cores = body.cores or specs.get("cores", 1)
    new_ram = body.memory_mb or specs.get("memory_mb", 1024)
    disk = specs.get("disk_gb", 32)

    spec_errors = validate_instance_specs(new_cores, new_ram, disk)
    if spec_errors:
        raise HTTPException(status_code=422, detail=[{"field": e.field, "message": e.message} for e in spec_errors])

    # Quota check
    quota = await _get_quota(db, user.id)
    if new_cores > quota.max_vcpus:
        raise HTTPException(status_code=403, detail=f"vCPU quota exceeded ({quota.max_vcpus} max)")

    try:
        if resource.resource_type == "lxc":
            proxmox_client.set_container_config(resource.proxmox_node, resource.proxmox_vmid, cores=new_cores, memory=new_ram)
        else:
            proxmox_client.resize_vm(resource.proxmox_node, resource.proxmox_vmid, new_cores, new_ram)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    specs["cores"] = new_cores
    specs["memory_mb"] = new_ram
    resource.specs = json.dumps(specs)
    await db.commit()
    await log_action(db, user.id, "vm_resize", "vm", resource.id)
    return {"status": "ok", "specs": specs}


@router.get("/vms/{resource_id}/console")
async def vm_console(
    resource_id: str,
    console_type: str = "vnc",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get VNC or terminal proxy ticket for a VM.
    Returns ticket, port, and the Proxmox websocket URL to connect to.
    """
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="operate")
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"

    # Resolve actual node - VM may have migrated since DB record was written
    actual_node = proxmox_client.find_vm_node(resource.proxmox_vmid) or resource.proxmox_node
    if actual_node != resource.proxmox_node:
        resource.proxmox_node = actual_node
        await db.commit()

    try:
        if console_type == "terminal":
            ticket_data = proxmox_client.get_terminal_proxy(actual_node, resource.proxmox_vmid, vmtype=vmtype)
        else:
            ticket_data = proxmox_client.get_vnc_ticket(actual_node, resource.proxmox_vmid, vmtype=vmtype)
        ticket_data["node"] = actual_node
        ticket_data["vmid"] = resource.proxmox_vmid
        ticket_data["vmtype"] = vmtype
        return ticket_data
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.websocket("/ws/console/{resource_id}")
async def ws_console_proxy(websocket: WebSocket, resource_id: str):
    """WebSocket proxy to Proxmox VNC/terminal websocket.
    Query params: token (JWT), type (vnc|terminal)
    """
    import websockets

    console_type = websocket.query_params.get("type", "vnc")

    # Authenticate via token query param
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4003, reason="Unauthorized")
        return
    from app.core.security import decode_token
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=4003, reason="Unauthorized")
        return
    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4003, reason="Unauthorized")
        return
    import uuid as _uuid
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        await websocket.close(code=4003, reason="Unauthorized")
        return
    user = None
    async for db in get_db():
        from sqlalchemy import select as _sel
        result = await db.execute(_sel(User).where(User.id == uid))
        user = result.scalar_one_or_none()
        break
    if not user or not user.is_active:
        await websocket.close(code=4003, reason="Unauthorized")
        return

    # Look up the resource and resolve actual node
    try:
        async for db in get_db():
            resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="operate")
            # Resolve actual node - VM may have migrated
            actual_node = proxmox_client.find_vm_node(resource.proxmox_vmid) or resource.proxmox_node
            if actual_node != resource.proxmox_node:
                print(f"[CONSOLE] Node corrected: DB={resource.proxmox_node} -> actual={actual_node}", flush=True)
                resource.proxmox_node = actual_node
                db.add(resource)
                await db.commit()
            break
    except Exception as e:
        print(f"[CONSOLE] Resource lookup failed: {e}", flush=True)
        await websocket.close(code=4004, reason="Resource not found")
        return

    # Get proxy ticket from Proxmox
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
    session_user = None
    session_ticket = None
    try:
        if console_type == "terminal":
            # Terminal requires a PVE session ticket (API tokens not supported by termproxy)
            try:
                session_user, session_ticket = proxmox_client.get_session_ticket()
            except Exception as se:
                print(f"[CONSOLE] Session ticket error: {se}", flush=True)
                await websocket.close(code=4502, reason="Terminal requires PAWS_PROXMOX_PASSWORD")
                return
            ticket_data = proxmox_client.get_terminal_proxy(resource.proxmox_node, resource.proxmox_vmid, vmtype=vmtype)
        else:
            ticket_data = proxmox_client.get_vnc_ticket(resource.proxmox_node, resource.proxmox_vmid, vmtype=vmtype)
        print(f"[CONSOLE] Got ticket for {console_type}, port={ticket_data.get('port')}", flush=True)
    except Exception as e:
        print(f"[CONSOLE] Failed to get ticket: {e}", flush=True)
        await websocket.close(code=4502, reason="Failed to get console ticket")
        return

    port = ticket_data.get("port")
    ticket = ticket_data.get("ticket")
    pve_host = settings.proxmox_host.replace("https://", "").replace("http://", "").split(":")[0].rstrip("/")
    pve_port = settings.proxmox_port
    vmid = resource.proxmox_vmid
    node = resource.proxmox_node  # Already resolved to actual node above

    from urllib.parse import quote
    encoded_ticket = quote(ticket, safe="")

    # Both VNC and terminal use the vncwebsocket endpoint for the WS connection
    pve_type = "lxc" if resource.resource_type == "lxc" else "qemu"
    ws_path = f"/api2/json/nodes/{node}/{pve_type}/{vmid}/vncwebsocket?port={port}&vncticket={encoded_ticket}"

    proxmox_ws_url = f"wss://{pve_host}:{pve_port}{ws_path}"

    ssl_ctx = ssl.create_default_context()
    if not settings.proxmox_verify_ssl:
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    await websocket.accept(subprotocol="binary")

    print(f"[CONSOLE] WS accepted, connecting to PVE: wss://{pve_host}:{pve_port}/...{node}/{vmid} type={console_type}", flush=True)

    pve_ws = None
    try:
        pve_token_id = settings.proxmox_token_id
        pve_token_secret = settings.proxmox_token_secret
        auth_header = f"PVEAPIToken={pve_token_id}={pve_token_secret}"
        pve_ws = await websockets.connect(
            proxmox_ws_url,
            ssl=ssl_ctx,
            subprotocols=["binary"],
            additional_headers={"Authorization": auth_header},
            open_timeout=10,
            compression=None,
        )
        print(f"[CONSOLE] PVE WS connected, subprotocol={pve_ws.subprotocol}", flush=True)

        # Terminal proxy requires sending user:ticket as first message
        # (uses session ticket, not VNC ticket - termproxy validates via /access/ticket)
        if console_type == "terminal" and session_user and session_ticket:
            auth_msg = f"{session_user}:{session_ticket}\n"
            await pve_ws.send(auth_msg)
            print(f"[CONSOLE] Sent terminal auth for user={session_user}", flush=True)
            try:
                resp = await asyncio.wait_for(pve_ws.recv(), timeout=5)
                resp_text = resp if isinstance(resp, str) else resp.decode("utf-8", errors="replace")
                if resp_text.strip() != "OK":
                    print(f"[CONSOLE] Terminal auth rejected: {resp_text!r}", flush=True)
                    await websocket.close(code=4503, reason="Terminal auth rejected")
                    return
                print("[CONSOLE] Terminal auth OK", flush=True)
            except asyncio.TimeoutError:
                print("[CONSOLE] Terminal auth response timed out", flush=True)
            except Exception as auth_err:
                print(f"[CONSOLE] Terminal auth failed: {auth_err}", flush=True)
                await websocket.close(code=4503, reason="Terminal auth failed")
                return
    except Exception as exc:
        print(f"[CONSOLE] PVE WS connect failed: {type(exc).__name__}: {exc}", flush=True)
        try:
            await websocket.close(code=4502, reason="Failed to connect to Proxmox")
        except Exception:
            pass
        return

    try:
        msg_count_c2p = 0
        msg_count_p2c = 0
        closed = asyncio.Event()

        async def forward_client_to_proxmox():
            nonlocal msg_count_c2p
            try:
                while not closed.is_set():
                    msg = await websocket.receive()
                    msg_type = msg.get("type", "")
                    if msg_type == "websocket.receive":
                        data = msg.get("bytes") or msg.get("text")
                        if data:
                            msg_count_c2p += 1
                            if msg_count_c2p <= 5:
                                print(f"[CONSOLE] Client->PVE #{msg_count_c2p}: {type(data).__name__} len={len(data)}", flush=True)
                            await pve_ws.send(data)
                    elif msg_type == "websocket.disconnect":
                        print("[CONSOLE] Client disconnected", flush=True)
                        break
                    else:
                        print(f"[CONSOLE] Client msg type: {msg_type}", flush=True)
            except WebSocketDisconnect:
                print("[CONSOLE] Client WebSocketDisconnect", flush=True)
            except Exception as e:
                if not closed.is_set():
                    print(f"[CONSOLE] Client->PVE error: {type(e).__name__}: {e}", flush=True)
            finally:
                closed.set()

        async def forward_proxmox_to_client():
            nonlocal msg_count_p2c
            try:
                async for msg in pve_ws:
                    if closed.is_set():
                        break
                    msg_count_p2c += 1
                    if msg_count_p2c <= 5:
                        preview = msg[:30] if isinstance(msg, bytes) else msg[:30]
                        print(f"[CONSOLE] PVE->Client #{msg_count_p2c}: {type(msg).__name__} len={len(msg)} preview={preview!r}", flush=True)
                    if isinstance(msg, bytes):
                        await websocket.send_bytes(msg)
                    else:
                        await websocket.send_text(msg)
            except Exception as e:
                if not closed.is_set():
                    print(f"[CONSOLE] PVE->Client error: {type(e).__name__}: {e}", flush=True)
            finally:
                closed.set()
            print(f"[CONSOLE] PVE->Client loop ended, total msgs: {msg_count_p2c}", flush=True)

        print("[CONSOLE] Starting bidirectional proxy...", flush=True)
        await asyncio.gather(forward_client_to_proxmox(), forward_proxmox_to_client())
    except Exception as exc:
        print(f"[CONSOLE] Proxy loop error: {type(exc).__name__}: {exc}", flush=True)
    finally:
        print("[CONSOLE] Cleaning up connections", flush=True)
        try:
            await pve_ws.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/vms/{resource_id}/snapshots")
async def list_vm_snapshots(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_user_resource(db, user.id, resource_id, "vm")
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
    try:
        return proxmox_client.list_snapshots(resource.proxmox_node, resource.proxmox_vmid, vmtype=vmtype)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/vms/{resource_id}/snapshots")
async def create_vm_snapshot(
    resource_id: str,
    body: SnapshotRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
    try:
        upid = proxmox_client.create_snapshot(
            resource.proxmox_node, resource.proxmox_vmid, body.name, vmtype=vmtype, description=body.description
        )
        await log_action(db, user.id, "snapshot_create", resource.resource_type, resource.id, {"snapshot": body.name})
        return {"status": "ok", "task": upid}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/vms/{resource_id}/snapshots/{snapname}/rollback")
async def rollback_vm_snapshot(
    resource_id: str,
    snapname: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
    try:
        upid = proxmox_client.rollback_snapshot(
            resource.proxmox_node, resource.proxmox_vmid, snapname, vmtype=vmtype
        )
        await log_action(db, user.id, "snapshot_rollback", resource.resource_type, resource.id, {"snapshot": snapname})
        return {"status": "ok", "task": upid}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/vms/{resource_id}/snapshots/{snapname}")
async def delete_vm_snapshot(
    resource_id: str,
    snapname: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
    try:
        upid = proxmox_client.delete_snapshot(
            resource.proxmox_node, resource.proxmox_vmid, snapname, vmtype=vmtype
        )
        await log_action(db, user.id, "snapshot_delete", resource.resource_type, resource.id, {"snapshot": snapname})
        return {"status": "ok", "task": upid}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/vms/{resource_id}/metrics")
async def vm_metrics(
    resource_id: str,
    timeframe: str = "hour",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get RRD metrics (CPU, memory, network, disk IO) for a VM.
    timeframe: hour, day, week, month, year
    """
    resource = await _get_user_resource(db, user.id, resource_id, "vm")
    if timeframe not in ("hour", "day", "week", "month", "year"):
        raise HTTPException(status_code=400, detail="Invalid timeframe")
    try:
        data = proxmox_client.get_rrd_data(resource.proxmox_node, resource.proxmox_vmid, vmtype="lxc" if resource.resource_type == "lxc" else "qemu", timeframe=timeframe)
        # Downsample to max 60 points for chart readability
        max_points = 60
        if len(data) > max_points:
            step = len(data) / max_points
            data = [data[int(i * step)] for i in range(max_points)]
        return {"timeframe": timeframe, "data": data}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/vms/{resource_id}/tasks")
async def vm_tasks(
    resource_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get Proxmox task history for a VM."""
    resource = await _get_user_resource(db, user.id, resource_id, "vm")
    try:
        tasks = proxmox_client.get_node_tasks(resource.proxmox_node, vmid=resource.proxmox_vmid, limit=limit)
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/vms/{resource_id}/network")
async def vm_network(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get network interfaces configuration for a VM, plus user's available VPCs."""
    resource = await _get_user_resource(db, user.id, resource_id, "vm")
    try:
        if resource.resource_type == "lxc":
            config = proxmox_client.get_container_config(resource.proxmox_node, resource.proxmox_vmid)
        else:
            config = proxmox_client.get_vm_config(resource.proxmox_node, resource.proxmox_vmid)
        nets = {}
        for key, val in config.items():
            if key.startswith("net") and key[3:].isdigit():
                nets[key] = val
        specs = json.loads(resource.specs) if resource.specs else {}

        # Try to get IP addresses from guest agent (VMs) or LXC net config
        ip_addresses: dict[str, list[str]] = {}
        if resource.resource_type == "qemu":
            try:
                ifaces = proxmox_client.get_agent_network_interfaces(
                    resource.proxmox_node, resource.proxmox_vmid
                )
                for iface in ifaces:
                    name = iface.get("name", "")
                    ips = [
                        a["ip-address"]
                        for a in iface.get("ip-addresses", [])
                        if a.get("ip-address-type") in ("ipv4", "ipv6")
                        and not a.get("ip-address", "").startswith("fe80:")
                    ]
                    if ips:
                        ip_addresses[name] = ips
            except Exception:
                pass
        elif resource.resource_type == "lxc":
            for key, val in nets.items():
                if isinstance(val, str):
                    iface_ips = []
                    for part in val.split(","):
                        if part.startswith("ip=") and part != "ip=dhcp":
                            iface_ips.append(part[3:].split("/")[0])
                    if iface_ips:
                        ip_addresses[key] = iface_ips

        # Fetch user's VPCs
        from app.models.models import VPC
        vpc_result = await db.execute(
            select(VPC).where(VPC.owner_id == user.id, VPC.status == "active")
        )
        vpcs = vpc_result.scalars().all()
        vpc_list = [
            {"id": str(v.id), "name": v.name, "vnet": v.proxmox_vnet, "vxlan_tag": v.vxlan_tag, "cidr": v.cidr, "network_mode": v.network_mode or "private"}
            for v in vpcs
        ]
        return {
            "interfaces": nets,
            "ip_addresses": ip_addresses,
            "vpc_id": specs.get("vpc_id"),
            "vpcs": vpc_list,
            "resource_type": resource.resource_type,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class VMNetworkUpdateRequest(BaseModel):
    net_id: str = "net0"
    vpc_id: str  # Must be one of user's VPCs
    model: str = "virtio"
    firewall: int = 1


@router.put("/vms/{resource_id}/network")
async def update_vm_network(
    resource_id: str,
    body: VMNetworkUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Update a VM's network interface to use a specific user VPC with static IP."""
    import ipaddress as _ipaddr
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")

    # Validate the VPC belongs to this user
    from app.models.models import IPReservation, VPC
    import uuid as _uuid
    try:
        vpc_uuid = _uuid.UUID(body.vpc_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid VPC ID")
    vpc_result = await db.execute(
        select(VPC).where(VPC.id == vpc_uuid, VPC.owner_id == user.id)
    )
    vpc = vpc_result.scalar_one_or_none()
    if not vpc:
        raise HTTPException(status_code=404, detail="VPC not found or not owned by you")
    if not vpc.proxmox_vnet:
        raise HTTPException(status_code=400, detail="VPC has no Proxmox vnet configured")

    # Release any old IP reservations for this resource
    await db.execute(
        delete(IPReservation).where(IPReservation.resource_id == resource.id)
    )

    # Auto-allocate static IP from first active subnet
    subnet_result = await db.execute(
        select(Subnet).where(Subnet.vpc_id == vpc.id, Subnet.status == "active")
        .options(selectinload(Subnet.ip_reservations))
        .limit(1)
    )
    subnet = subnet_result.scalar_one_or_none()

    ip_str = None
    prefix_len = None
    gateway = None
    if subnet:
        try:
            network = _ipaddr.ip_network(subnet.cidr, strict=False)
            prefix_len = network.prefixlen
            gateway = subnet.gateway or str(list(network.hosts())[0])
            used_ips = {r.ip_address for r in subnet.ip_reservations}
            for host in list(network.hosts())[1:]:
                if str(host) not in used_ips:
                    ip_str = str(host)
                    break
            if ip_str:
                db.add(IPReservation(
                    subnet_id=subnet.id, ip_address=ip_str, resource_id=resource.id,
                    label=resource.display_name, is_gateway=False, owner_id=user.id,
                ))
        except Exception:
            logger.warning("Failed to allocate IP for network change on %s", resource_id, exc_info=True)

    # Build and apply the NIC via unified helpers
    vmtype = resource.resource_type if resource.resource_type == "lxc" else "qemu"
    try:
        net0_val = _build_net0(
            vmtype, vpc.proxmox_vnet,
            ip=ip_str, prefix_len=prefix_len, gateway=gateway,
            firewall=body.firewall, model=body.model,
        )
        dns = (subnet.dns_server or "1.1.1.1") if subnet else "1.1.1.1"

        # Check if running - NIC bridge changes require stop/start for VMs
        was_running = False
        if vmtype != "lxc":
            try:
                st = proxmox_client.get_vm_status(resource.proxmox_node, resource.proxmox_vmid)
                was_running = st.get("status") == "running"
                if was_running:
                    upid = proxmox_client.stop_vm(resource.proxmox_node, resource.proxmox_vmid)
                    proxmox_client.wait_for_task(resource.proxmox_node, upid, timeout=60)
            except Exception:
                pass
        else:
            try:
                st = proxmox_client.get_container_status(resource.proxmox_node, resource.proxmox_vmid)
                was_running = st.get("status") == "running"
                if was_running:
                    upid = proxmox_client.stop_container(resource.proxmox_node, resource.proxmox_vmid)
                    proxmox_client.wait_for_task(resource.proxmox_node, upid, timeout=60)
            except Exception:
                pass

        # For net0, use _apply_nic; for other NICs, apply directly
        if body.net_id == "net0":
            _apply_nic(
                resource.proxmox_node, resource.proxmox_vmid, vmtype, net0_val,
                ip=ip_str, prefix_len=prefix_len, gateway=gateway,
                dns_server=dns,
            )
        else:
            if vmtype == "lxc":
                proxmox_client.set_container_config(
                    resource.proxmox_node, resource.proxmox_vmid, **{body.net_id: net0_val}
                )
            else:
                proxmox_client.update_vm_config(
                    resource.proxmox_node, resource.proxmox_vmid, **{body.net_id: net0_val}
                )

        specs = json.loads(resource.specs) if resource.specs else {}
        specs["vpc_id"] = str(vpc.id)
        if ip_str:
            specs["ip_address"] = ip_str
        resource.specs = json.dumps(specs)
        await db.commit()

        # Restart if it was running before the NIC change
        if was_running:
            try:
                if vmtype == "lxc":
                    proxmox_client.start_container(resource.proxmox_node, resource.proxmox_vmid)
                else:
                    proxmox_client.start_vm(resource.proxmox_node, resource.proxmox_vmid)
            except Exception:
                pass

        return {
            "status": "ok",
            "vpc": {"id": str(vpc.id), "name": vpc.name, "vnet": vpc.proxmox_vnet},
            "ip_address": ip_str,
            "restarted": was_running,
            "message": "Instance was restarted to apply the network change." if was_running else "Network updated.",
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class NICAddRequest(BaseModel):
    vpc_id: str
    model: str = "virtio"
    firewall: int = 1


@router.post("/vms/{resource_id}/network/nics")
async def add_nic(
    resource_id: str,
    body: NICAddRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Add a secondary network interface to an instance.

    Rules:
    - Published primary network: max 1 NIC (no additional NICs allowed)
    - Isolated primary network: no secondary NICs allowed
    - Private primary network: can add NICs for each private network owned
    - Secondary NICs must target private networks
    - Cannot attach the same network twice
    """
    import ipaddress as _ipaddr
    import uuid as _uuid
    from app.models.models import IPReservation, VPC

    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")

    if resource.resource_type == "lxc":
        config = proxmox_client.get_container_config(resource.proxmox_node, resource.proxmox_vmid)
    else:
        config = proxmox_client.get_vm_config(resource.proxmox_node, resource.proxmox_vmid)
    existing = [k for k in config if k.startswith("net") and k[3:].isdigit()]

    # Check primary VPC mode
    specs = json.loads(resource.specs) if resource.specs else {}
    primary_vpc_id = specs.get("vpc_id")
    if primary_vpc_id:
        primary_vpc_row = await db.execute(
            select(VPC).where(VPC.id == _uuid.UUID(primary_vpc_id))
        )
        primary_vpc = primary_vpc_row.scalar_one_or_none()
        if primary_vpc:
            if primary_vpc.network_mode == "isolated":
                raise HTTPException(
                    status_code=400,
                    detail="Cannot add secondary NIC to an instance on an isolated network",
                )
            if primary_vpc.network_mode == "published" and len(existing) >= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Published networks only allow a single network interface",
                )

    # Target VPC must be private and owned by user
    vpc = (await db.execute(
        select(VPC).where(VPC.id == _uuid.UUID(body.vpc_id), VPC.owner_id == user.id)
    )).scalar_one_or_none()
    if not vpc or not vpc.proxmox_vnet:
        raise HTTPException(status_code=404, detail="Network not found or has no VNet")
    if vpc.network_mode != "private":
        raise HTTPException(
            status_code=400,
            detail="Secondary NICs can only be attached to private networks",
        )

    # Check for duplicate - cannot attach same VNet twice
    for key in existing:
        val = config.get(key, "")
        if isinstance(val, str) and f"bridge={vpc.proxmox_vnet}" in val:
            raise HTTPException(
                status_code=409,
                detail=f"Network '{vpc.name}' is already attached to this instance",
            )

    next_idx = max((int(k[3:]) for k in existing), default=-1) + 1
    net_id = f"net{next_idx}"

    # Auto-allocate static IP from the target VPC's subnet
    subnet_result = await db.execute(
        select(Subnet).where(Subnet.vpc_id == vpc.id, Subnet.status == "active")
        .options(selectinload(Subnet.ip_reservations))
        .limit(1)
    )
    subnet = subnet_result.scalar_one_or_none()

    ip_str = None
    prefix_len = None
    gateway = None
    if subnet:
        try:
            network = _ipaddr.ip_network(subnet.cidr, strict=False)
            prefix_len = network.prefixlen
            gateway = subnet.gateway or str(list(network.hosts())[0])
            used_ips = {r.ip_address for r in subnet.ip_reservations}
            for host in list(network.hosts())[1:]:
                if str(host) not in used_ips:
                    ip_str = str(host)
                    break
            if not ip_str:
                raise HTTPException(status_code=409, detail="No available IPs in the target network subnet")
        except HTTPException:
            raise
        except Exception:
            logger.warning("Failed to allocate IP for secondary NIC", exc_info=True)

    net_val = _build_net0(
        resource.resource_type, vpc.proxmox_vnet,
        ip=ip_str, prefix_len=prefix_len, gateway=gateway,
        firewall=body.firewall, model=body.model,
        iface_name=f"eth{next_idx}" if resource.resource_type == "lxc" else None,
    )

    try:
        if resource.resource_type == "lxc":
            proxmox_client.update_container_config(resource.proxmox_node, resource.proxmox_vmid, **{net_id: net_val})
        else:
            proxmox_client.update_vm_config(resource.proxmox_node, resource.proxmox_vmid, **{net_id: net_val})

        # Set cloud-init ipconfig for secondary NIC (VMs only)
        if resource.resource_type == "qemu" and ip_str and prefix_len:
            ipconfig_key = f"ipconfig{next_idx}"
            ipconfig_val = f"ip={ip_str}/{prefix_len}"
            if gateway:
                ipconfig_val += f",gw={gateway}"
            proxmox_client.update_vm_config(resource.proxmox_node, resource.proxmox_vmid, **{ipconfig_key: ipconfig_val})
            proxmox_client.regenerate_cloudinit(resource.proxmox_node, resource.proxmox_vmid)

        # Create IP reservation
        if ip_str and subnet:
            db.add(IPReservation(
                subnet_id=subnet.id, ip_address=ip_str, resource_id=resource.id,
                label=f"{resource.display_name}-{net_id}", is_gateway=False, owner_id=user.id,
            ))

        # Track secondary VPC in specs
        secondary_vpc_ids = specs.get("secondary_vpc_ids", [])
        secondary_vpc_ids.append(str(vpc.id))
        specs["secondary_vpc_ids"] = secondary_vpc_ids
        resource.specs = json.dumps(specs)
        await db.commit()

        return {
            "status": "ok", "net_id": net_id, "value": net_val,
            "ip_address": ip_str, "vpc_id": str(vpc.id),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/vms/{resource_id}/network/nics/{net_id}")
async def remove_nic(
    resource_id: str,
    net_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Remove a secondary network interface from an instance (cannot remove net0)."""
    from app.models.models import IPReservation

    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")
    if net_id == "net0":
        raise HTTPException(status_code=400, detail="Cannot remove primary interface net0")
    if not (net_id.startswith("net") and net_id[3:].isdigit()):
        raise HTTPException(status_code=400, detail="Invalid NIC id")

    net_idx = int(net_id[3:])

    try:
        if resource.resource_type == "lxc":
            proxmox_client.update_container_config(
                resource.proxmox_node, resource.proxmox_vmid, delete=net_id
            )
        else:
            # Remove NIC config
            proxmox_client.update_vm_config(
                resource.proxmox_node, resource.proxmox_vmid, delete=net_id
            )
            # Remove cloud-init ipconfig for this NIC
            ipconfig_key = f"ipconfig{net_idx}"
            try:
                proxmox_client.update_vm_config(
                    resource.proxmox_node, resource.proxmox_vmid, delete=ipconfig_key
                )
                proxmox_client.regenerate_cloudinit(resource.proxmox_node, resource.proxmox_vmid)
            except Exception:
                logger.debug("No ipconfig%d to remove", net_idx)

        # Release IP reservations for this NIC
        label_pattern = f"{resource.display_name}-{net_id}"
        ip_rows = await db.execute(
            select(IPReservation).where(
                IPReservation.resource_id == resource.id,
                IPReservation.label == label_pattern,
            )
        )
        for ip_res in ip_rows.scalars().all():
            await db.delete(ip_res)

        # Remove secondary VPC from specs
        specs = json.loads(resource.specs) if resource.specs else {}
        secondary_vpc_ids = specs.get("secondary_vpc_ids", [])
        if secondary_vpc_ids:
            specs["secondary_vpc_ids"] = secondary_vpc_ids[:-1]  # remove last added
            resource.specs = json.dumps(specs)

        await db.commit()
        return {"status": "ok", "removed": net_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Cloud-Init / Instance Configuration ---


class InstanceConfigRequest(BaseModel):
    """Structured cloud-init (VM) / LXC config fields."""
    username: str | None = None
    password: str | None = None
    ssh_key_ids: list[str] | None = None
    dns_domain: str | None = None
    dns_server: str | None = None
    hostname: str | None = None


@router.get("/vms/{resource_id}/config")
async def get_instance_config(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get the current cloud-init (VM) or LXC configuration for an instance."""
    resource = await _get_user_resource(db, user.id, resource_id, "vm")
    node = resource.proxmox_node
    vmid = resource.proxmox_vmid

    result: dict = {
        "resource_type": resource.resource_type,
        "username": None,
        "password_set": False,
        "ssh_key_ids": [],
        "dns_domain": None,
        "dns_server": None,
        "hostname": None,
        "ip_address": None,
    }

    # Load user's saved SSH keys for matching
    user_keys_result = await db.execute(
        select(SSHKeyPair).where(SSHKeyPair.owner_id == user.id)
    )
    user_keys = {k.public_key.strip(): str(k.id) for k in user_keys_result.scalars().all()}

    try:
        if resource.resource_type == "qemu":
            config = proxmox_client.get_vm_config(node, vmid)
            result["username"] = config.get("ciuser")
            result["password_set"] = bool(config.get("cipassword"))
            raw_keys = config.get("sshkeys", "")
            if raw_keys:
                import urllib.parse
                decoded = urllib.parse.unquote(raw_keys)
                installed_keys = [k.strip() for k in decoded.strip().split("\n") if k.strip()]
                matched_ids = [user_keys[k] for k in installed_keys if k in user_keys]
                result["ssh_key_ids"] = matched_ids
            result["dns_domain"] = config.get("searchdomain") or None
            result["dns_server"] = config.get("nameserver") or None
            result["hostname"] = config.get("name") or None
            ipconfig0 = config.get("ipconfig0", "")
            if ipconfig0 and "ip=" in ipconfig0:
                for part in ipconfig0.split(","):
                    if part.startswith("ip="):
                        result["ip_address"] = part[3:]
        elif resource.resource_type == "lxc":
            config = proxmox_client.get_container_config(node, vmid)
            result["hostname"] = config.get("hostname") or None
            result["dns_domain"] = config.get("searchdomain") or None
            result["dns_server"] = config.get("nameserver") or None
            raw_keys = config.get("ssh-public-keys", "")
            if raw_keys:
                installed_keys = [k.strip() for k in raw_keys.strip().split("\n") if k.strip()]
                matched_ids = [user_keys[k] for k in installed_keys if k in user_keys]
                result["ssh_key_ids"] = matched_ids
            net0 = config.get("net0", "")
            if isinstance(net0, str):
                for part in net0.split(","):
                    if part.startswith("ip=") and part != "ip=dhcp":
                        result["ip_address"] = part[3:]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to read config: {e}")

    # Get allocated IP from database
    from app.models.models import IPReservation
    ip_res = await db.execute(
        select(IPReservation).where(IPReservation.resource_id == resource.id)
    )
    reservations = ip_res.scalars().all()
    if reservations:
        result["allocated_ip"] = reservations[0].ip_address
    else:
        result["allocated_ip"] = None

    return result


@router.put("/vms/{resource_id}/config")
async def update_instance_config(
    resource_id: str,
    body: InstanceConfigRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Update cloud-init (VM) or LXC configuration for an instance.

    All fields are optional. Only provided fields are updated.
    IP address changes should go through the VPC IP change endpoint.
    """
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")
    node = resource.proxmox_node
    vmid = resource.proxmox_vmid

    # Resolve SSH key IDs to actual public keys
    resolved_keys: list[str] | None = None
    if body.ssh_key_ids is not None:
        resolved_keys = await _resolve_ssh_keys(db, user.id, body.ssh_key_ids) if body.ssh_key_ids else []

    try:
        _apply_instance_config(
            node, vmid, resource.resource_type,
            username=body.username,
            password=body.password,
            hostname=body.hostname,
            dns_server=body.dns_server,
            dns_domain=body.dns_domain,
            ssh_public_keys=resolved_keys,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to update config: {e}")

    changed = {k: v for k, v in body.model_dump().items() if v is not None}
    if "password" in changed:
        changed["password"] = "***"
    await log_action(db, user.id, "config_update", resource_id=str(resource.id),
                     details=f"Config updated: {', '.join(changed.keys())}")
    await db.commit()
    return {"status": "ok", "updated_fields": list(changed.keys())}



async def list_backup_storages(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List admin-configured backup storages available to the current user."""
    import json as _json

    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "backup_storages")
    )
    setting = result.scalar_one_or_none()
    allowed = _json.loads(setting.value) if setting else []
    if not allowed:
        return []
    # Return as objects with storage name
    return [{"storage": name} for name in allowed]


@router.get("/backup-storages/available")
async def list_available_backup_storages(
    _: User = Depends(require_admin),
):
    """Admin-only: list all Proxmox storages that support backups."""
    try:
        storages = proxmox_client.get_storage_list()
        result = []
        for s in storages:
            if "backup" in s.get("content", ""):
                result.append({
                    "storage": s["storage"],
                    "type": s.get("type", ""),
                    "shared": bool(s.get("shared", 0)),
                })
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/vms/{resource_id}/backups")
async def vm_backups(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List backup files for a VM. Filters by user ID tag in notes."""
    resource = await _get_user_resource(db, user.id, resource_id, "vm")
    backups: list[dict] = []
    user_tag = f"[paws:{user.id}]"
    vmid_str = str(resource.proxmox_vmid)

    # Scan all PVE backup-capable storages (including PBS-type)
    try:
        storages = proxmox_client.get_storage_list()
        for s in storages:
            if "backup" not in s.get("content", ""):
                continue
            try:
                contents = proxmox_client.get_storage_content(
                    s.get("node", resource.proxmox_node), s["storage"]
                )
                is_pbs = s.get("type") == "pbs"
                for item in contents:
                    if item.get("content") != "backup":
                        continue
                    if vmid_str not in item.get("volid", ""):
                        continue
                    notes = item.get("notes", "") or ""
                    if user_tag not in notes:
                        continue
                    entry: dict = {
                        "volid": item.get("volid"),
                        "size": item.get("size", 0),
                        "ctime": item.get("ctime", 0),
                        "format": item.get("format", "pbs" if is_pbs else ""),
                        "storage": s["storage"],
                        "notes": notes,
                        "pbs": is_pbs,
                    }
                    if is_pbs:
                        entry["backup_type"] = "ct" if "/ct/" in item.get("volid", "") else "vm"
                        entry["backup_id"] = vmid_str
                        entry["backup_time"] = item.get("ctime", 0)
                    backups.append(entry)
            except Exception:
                pass
    except Exception:
        pass

    backups.sort(key=lambda b: b.get("ctime", 0), reverse=True)
    return {"backups": backups}


class VMBackupRequest(BaseModel):
    storage: str = "local"
    mode: str = "snapshot"
    compress: str = "zstd"
    notes: str | None = None


@router.post("/vms/{resource_id}/backups")
async def create_vm_backup(
    resource_id: str,
    body: VMBackupRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Create a backup of a VM. Auto-creates PBS namespace for user isolation."""
    import json as _json
    from typing import Any as _Any
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="operate")

    # Check backup quota
    quota_result = await db.execute(select(UserQuota).where(UserQuota.user_id == user.id))
    user_quota = quota_result.scalar_one_or_none()
    max_backups = user_quota.max_backups if user_quota else 20
    user_tag = f"[paws:{user.id}]"
    current_count = 0
    try:
        storages = proxmox_client.get_storage_list()
        for st in storages:
            if "backup" not in st.get("content", ""):
                continue
            try:
                node = st.get("node") or resource.proxmox_node
                contents = proxmox_client.get_storage_content(node, st["storage"])
                for item in contents:
                    if item.get("content") == "backup" and user_tag in (item.get("notes", "") or ""):
                        current_count += 1
            except Exception:
                pass
    except Exception:
        pass
    if current_count >= max_backups:
        raise HTTPException(status_code=409, detail=f"Backup quota exceeded ({current_count}/{max_backups}). Delete old backups or request a quota increase.")

    # Validate storage against admin-configured list
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "backup_storages")
    )
    setting = result.scalar_one_or_none()
    allowed = _json.loads(setting.value) if setting else []
    if not allowed:
        raise HTTPException(status_code=400, detail="No backup storages configured. Contact administrator.")
    if body.storage not in allowed:
        raise HTTPException(status_code=403, detail=f"Storage '{body.storage}' is not enabled for backups")

    try:
        kwargs: dict[str, _Any] = {
            "storage": body.storage,
            "mode": body.mode,
            "compress": body.compress,
        }
        auto_note = (
            f"{user_tag} PAWS backup | {resource.display_name}"
            f" | VMID {resource.proxmox_vmid} | {resource.proxmox_node}"
            f" | user: {user.username}"
        )
        if body.notes:
            auto_note = f"{auto_note} | {body.notes}"
        kwargs["notes-template"] = auto_note
        upid = proxmox_client.create_backup(resource.proxmox_node, resource.proxmox_vmid, **kwargs)
        await log_action(db, user.id, "vm_backup", "vm", resource.id, {"storage": body.storage})
        return {"status": "ok", "task": upid}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class BackupDeleteRequest(BaseModel):
    volid: str
    storage: str
    pbs: bool = False
    backup_type: str = "vm"
    backup_id: str = ""
    backup_time: int = 0


@router.delete("/vms/{resource_id}/backups")
async def delete_vm_backup(
    resource_id: str,
    body: BackupDeleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Delete a backup file via PVE API."""
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")

    try:
        proxmox_client.delete_storage_content(resource.proxmox_node, body.storage, body.volid)
        await log_action(db, user.id, "backup_delete", "vm", resource.id, {"volid": body.volid})
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class BackupRestoreRequest(BaseModel):
    volid: str
    storage: str
    pbs: bool = False


@router.post("/vms/{resource_id}/backups/restore")
async def restore_vm_backup(
    resource_id: str,
    body: BackupRestoreRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Restore a VM from a backup (overwrites current state)."""
    resource = await _get_user_resource(db, user.id, resource_id, "vm", min_group_perm="admin")
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"

    try:
        if vmtype == "lxc":
            upid = proxmox_client.restore_ct_backup(
                resource.proxmox_node, resource.proxmox_vmid, body.volid,
            )
        else:
            upid = proxmox_client.restore_vm_backup(
                resource.proxmox_node, resource.proxmox_vmid, body.volid,
            )
        await log_action(db, user.id, "backup_restore", "vm", resource.id, {"volid": body.volid})
        return {"status": "restoring", "task": upid}
    except Exception as e:
        msg = str(e)
        if "can't overwrite running" in msg.lower() or "overwrite running" in msg.lower():
            raise HTTPException(status_code=409, detail="Cannot restore: the instance is currently running. Stop it first, then retry.")
        raise HTTPException(status_code=502, detail=msg)


class BackupFilesRequest(BaseModel):
    volid: str = ""
    storage: str = ""
    filepath: str = ""
    backup_type: str = "vm"
    backup_id: str = ""
    backup_time: int = 0


@router.post("/vms/{resource_id}/backups/files")
async def list_backup_files(
    resource_id: str,
    body: BackupFilesRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Browse files inside a backup snapshot via PVE file-restore API."""
    resource = await _get_user_resource(db, user.id, resource_id, "vm")

    try:
        logger.info("list_backup_files: node=%s storage=%s volid=%s filepath=%s",
                     resource.proxmox_node, body.storage, body.volid, body.filepath or "/")
        files = proxmox_client.list_backup_files(
            resource.proxmox_node, body.storage, body.volid, body.filepath or "/",
        )
        logger.info("list_backup_files returned: type=%s len=%s sample=%s",
                     type(files).__name__, len(files) if isinstance(files, list) else "N/A",
                     str(files)[:200] if files else "empty")
        return {"files": files}
    except Exception as e:
        logger.exception("list_backup_files failed")
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/vms/{resource_id}/backups/download")
async def download_backup_file(
    resource_id: str,
    body: BackupFilesRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Download a file/directory from a backup snapshot via PVE file-restore API."""
    from starlette.responses import Response
    resource = await _get_user_resource(db, user.id, resource_id, "vm")

    try:
        data = proxmox_client.download_backup_file(
            resource.proxmox_node, body.storage, body.volid, body.filepath,
        )
        # proxmoxer may return raw content in 'errors' key for non-JSON responses
        if isinstance(data, dict):
            content = data.get("errors", b"")
            if isinstance(content, str):
                content = content.encode()
        elif isinstance(data, bytes):
            content = data
        else:
            content = str(data).encode()
        filename = body.filepath.rsplit("/", 1)[-1] if "/" in body.filepath else body.filepath
        if not filename:
            filename = "download"
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


def _user_backup_tag(user: User) -> str:
    """Return the tag embedded in backup notes for ownership filtering."""
    return f"[paws:{user.id}]"


# --- Container Endpoints ---


@router.post("/containers", status_code=status.HTTP_202_ACCEPTED)
async def create_container(
    body: ContainerCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    if not body.template and not body.template_vmid:
        raise HTTPException(status_code=400, detail="Either 'template' (ostemplate) or 'template_vmid' is required")

    # Rate limit
    allowed, _ = await check_action_rate_limit(str(user.id), "container_create", 30)
    if not allowed:
        raise HTTPException(status_code=429, detail="Container creation rate limit exceeded (max 30/hour)")

    # Quota check
    quota = await _get_quota(db, user.id)
    ct_count = await _count_resources(db, user.id, "lxc")
    if ct_count >= quota.max_containers:
        raise HTTPException(status_code=403, detail=f"Container quota exceeded ({quota.max_containers} max)")

    pool_vmids = set((await db.execute(select(VMIDPool.vmid))).scalars().all())
    resource_vmids = set(
        (await db.execute(select(Resource.proxmox_vmid).where(Resource.proxmox_vmid.isnot(None)))).scalars().all()
    )
    existing = pool_vmids | resource_vmids
    vmid_start, vmid_end = await _get_vmid_range(db)
    new_vmid = get_next_vmid(existing, start=vmid_start, end=vmid_end)
    node = select_node("least-loaded")

    # Reserve VMID first
    db.add(VMIDPool(vmid=new_vmid, resource_id=None))
    await db.commit()

    try:
        if body.template_vmid:
            # Clone from CT template (same logic as VM cloning)
            template_node = proxmox_client.find_vm_node(body.template_vmid)
            if not template_node:
                raise RuntimeError(f"Template VMID {body.template_vmid} not found on any node")

            template_disk_storage = proxmox_client.get_container_disk_storage(template_node, body.template_vmid)
            storage_is_shared = (
                proxmox_client.is_storage_shared(template_disk_storage) if template_disk_storage else False
            )
            use_full_clone = not storage_is_shared
            needs_migration = template_node != node

            upid = proxmox_client.clone_container(
                node=template_node,
                source_vmid=body.template_vmid,
                new_vmid=new_vmid,
                hostname=body.name,
                full=int(use_full_clone),
                target=template_node,
                storage=body.storage if use_full_clone else None,
            )
            clone_node = template_node
        else:
            # Create from ostemplate tarball
            upid = proxmox_client.create_container(
                node=node,
                vmid=new_vmid,
                hostname=body.name,
                ostemplate=body.template,
                cores=body.cores,
                memory=body.memory_mb,
                rootfs=f"{body.storage}:{body.disk_gb}",
                net0=_build_net0("lxc", "vmbr0", link_down=True),
                start=0,
            )
            clone_node = node

        # Create the resource record
        resource = Resource(
            owner_id=user.id,
            resource_type="lxc",
            display_name=body.name,
            proxmox_vmid=new_vmid,
            proxmox_node=clone_node,
            status="provisioning",
            specs=json.dumps({"cores": body.cores, "memory_mb": body.memory_mb, "disk_gb": body.disk_gb}),
        )
        db.add(resource)
        vmid_result = await db.execute(select(VMIDPool).where(VMIDPool.vmid == new_vmid))
        vmid_entry = vmid_result.scalar_one_or_none()
        if vmid_entry:
            vmid_entry.resource_id = resource.id
        await db.commit()
        await log_action(db, user.id, "container_create", "lxc", resource.id, {"vmid": new_vmid})

        # Assign to Proxmox pool
        try:
            await ensure_user_pool(db, user)
            await add_resource_to_pool(db, user, new_vmid)
        except Exception:
            pass

        # Migrate to target node if cloned on a different node
        if body.template_vmid and needs_migration:
            try:
                proxmox_client.wait_for_task(clone_node, upid, timeout=120)
                proxmox_client.migrate_container(clone_node, new_vmid, target=node, online=False)
                resource.proxmox_node = node
                await db.commit()
            except Exception:
                pass  # Migration is best-effort; clone succeeded
        else:
            # Wait for create/clone to finish before reconfiguring
            try:
                proxmox_client.wait_for_task(clone_node, upid, timeout=120)
            except Exception:
                pass

        # Resolve SSH keys and apply instance configuration
        ct_ssh_keys = await _resolve_ssh_keys(db, user.id, body.ssh_key_ids)

        # Reconfigure specs and config after clone
        if body.template_vmid:
            try:
                proxmox_client.set_container_config(
                    resource.proxmox_node, new_vmid,
                    cores=body.cores, memory=body.memory_mb,
                )
                _apply_instance_config(
                    resource.proxmox_node, new_vmid, "lxc",
                    password=body.ci_password,
                    hostname=body.hostname,
                    dns_server=body.dns_server,
                    dns_domain=body.dns_domain,
                    ssh_public_keys=ct_ssh_keys if ct_ssh_keys else None,
                )
            except Exception as cfg_err:
                logger.error("Failed to apply container config for VMID %s: %s", new_vmid, cfg_err, exc_info=True)

        # Stamp PAWS ownership tags and notes on the Proxmox container
        _apply_paws_metadata(resource.proxmox_node, new_vmid, "lxc", user, resource)

        # Apply VPC networking (NIC bridge, bandwidth, firewall mode)
        await _resolve_vpc_networking(db, user, resource, body.vpc_id, body.network_mode)
        await db.commit()

        return {"id": str(resource.id), "vmid": new_vmid, "node": resource.proxmox_node, "status": "provisioning", "task": upid}
    except Exception as e:
        # Release VMID on failure
        result = await db.execute(select(VMIDPool).where(VMIDPool.vmid == new_vmid))
        vmid_entry = result.scalar_one_or_none()
        if vmid_entry:
            await db.delete(vmid_entry)
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Failed to create container: {e}")


@router.get("/containers")
async def list_containers(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(Resource)
        .where(
            Resource.owner_id == user.id,
            Resource.resource_type == "lxc",
            Resource.status.notin_(["destroyed", "error", "creating"]),
        )
        .order_by(Resource.created_at.desc())
    )
    resources = result.scalars().all()
    containers = []
    for r in resources:
        ct_data = {
            "id": str(r.id),
            "name": r.display_name,
            "vmid": r.proxmox_vmid,
            "node": r.proxmox_node,
            "status": r.status,
            "specs": json.loads(r.specs) if r.specs else {},
            "created_at": str(r.created_at),
            "last_accessed_at": r.last_accessed_at.isoformat() if r.last_accessed_at else None,
        }
        if r.status not in ("destroyed", "error", "creating") and r.proxmox_vmid and r.proxmox_node:
            try:
                live = proxmox_client.get_container_status(r.proxmox_node, r.proxmox_vmid)
                ct_data["live_status"] = live.get("status")
            except Exception:
                ct_data["live_status"] = "unknown"
        containers.append(ct_data)
    return containers


@router.get("/containers/{resource_id}")
async def get_container(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get a single container by resource ID with live status."""
    r = await _get_user_resource(db, user.id, resource_id, "lxc")
    ct_data = {
        "id": str(r.id),
        "display_name": r.display_name,
        "resource_type": r.resource_type,
        "proxmox_vmid": r.proxmox_vmid,
        "proxmox_node": r.proxmox_node,
        "status": r.status,
        "specs": json.loads(r.specs) if r.specs else {},
        "created_at": str(r.created_at),
        "last_accessed_at": r.last_accessed_at.isoformat() if r.last_accessed_at else None,
    }
    if r.status not in ("destroyed", "error", "creating") and r.proxmox_vmid and r.proxmox_node:
        try:
            live = proxmox_client.get_container_status(r.proxmox_node, r.proxmox_vmid)
            ct_data["live_status"] = live.get("status")
        except Exception:
            ct_data["live_status"] = "unknown"
    return ct_data


@router.post("/containers/{resource_id}/action")
async def container_action(
    resource_id: str,
    body: VMActionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_user_resource(db, user.id, resource_id, "lxc", min_group_perm="operate")
    node, vmid = resource.proxmox_node, resource.proxmox_vmid

    actions = {
        "start": proxmox_client.start_container,
        "stop": proxmox_client.stop_container,
        "shutdown": proxmox_client.shutdown_container,
    }
    if body.action not in actions:
        raise HTTPException(status_code=400, detail=f"Invalid action: {body.action}")

    # Enforce network safety before start
    if body.action == "start":
        try:
            _enforce_network_safety(resource)
        except ValueError as e:
            raise HTTPException(status_code=403, detail=str(e))

    try:
        upid = actions[body.action](node, vmid)
        await log_action(db, user.id, f"container_{body.action}", "lxc", resource.id)
        return {"status": "ok", "task": upid}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/containers/{resource_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_container(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    resource = await _get_user_resource(db, user.id, resource_id, "lxc", min_group_perm="admin")
    try:
        proxmox_client.stop_container(resource.proxmox_node, resource.proxmox_vmid)
    except Exception:
        pass
    try:
        proxmox_client.delete_container(resource.proxmox_node, resource.proxmox_vmid)
    except Exception:
        pass

    old_vmid = resource.proxmox_vmid
    # Free VMID pool entry
    result = await db.execute(select(VMIDPool).where(VMIDPool.vmid == old_vmid))
    vmid_entry = result.scalar_one_or_none()
    if vmid_entry:
        await db.delete(vmid_entry)
    # Clean up all child records referencing this resource
    await _cleanup_resource_children(db, resource.id)
    # Delete the resource record entirely
    await db.delete(resource)
    await db.commit()
    await log_action(db, user.id, "container_delete", "lxc", details={"vmid": old_vmid})
    return {"status": "destroyed"}


@router.post("/containers/{resource_id}/keepalive")
async def keepalive_container(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Touch last_accessed_at to prevent idle lifecycle enforcement."""
    r = await _get_user_resource(db, user.id, resource_id, "lxc")
    return {"last_accessed_at": r.last_accessed_at.isoformat() if r.last_accessed_at else None}


# --- Metadata Sync ---


@router.post("/instances/{resource_id}/sync-metadata")
async def sync_instance_metadata(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Re-stamp PAWS tags and notes on a single instance."""
    r = await _get_user_resource(db, user.id, resource_id, "vm")
    if not r.proxmox_vmid or not r.proxmox_node:
        raise HTTPException(status_code=400, detail="Resource has no Proxmox VMID/node")
    vmtype = "lxc" if r.resource_type == "lxc" else "qemu"
    _apply_paws_metadata(r.proxmox_node, r.proxmox_vmid, vmtype, user, r)
    return {"status": "ok"}


@router.post("/admin/sync-metadata")
async def admin_sync_all_metadata(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Re-stamp PAWS tags and notes on ALL active resources (admin only)."""
    result = await db.execute(
        select(Resource).where(
            Resource.status.notin_(["destroyed", "error"]),
            Resource.proxmox_vmid.isnot(None),
            Resource.proxmox_node.isnot(None),
        )
    )
    resources = result.scalars().all()
    success = 0
    failed = 0
    for r in resources:
        # Look up owner
        user_result = await db.execute(select(User).where(User.id == r.owner_id))
        owner = user_result.scalar_one_or_none()
        if not owner:
            failed += 1
            continue
        vmtype = "lxc" if r.resource_type == "lxc" else "qemu"
        try:
            _apply_paws_metadata(r.proxmox_node, r.proxmox_vmid, vmtype, owner, r)
            success += 1
        except Exception:
            failed += 1
    return {"synced": success, "failed": failed, "total": len(resources)}


# --- Helpers ---


async def _get_quota(db: AsyncSession, user_id: uuid.UUID) -> UserQuota:
    result = await db.execute(select(UserQuota).where(UserQuota.user_id == user_id))
    quota = result.scalar_one_or_none()
    if not quota:
        return UserQuota(
            max_vms=5, max_containers=10, max_vcpus=16, max_ram_mb=32768, max_disk_gb=500, max_snapshots=10
        )
    return quota


async def _count_resources(db: AsyncSession, user_id: uuid.UUID, resource_type: str) -> int:
    result = await db.execute(
        select(func.count(Resource.id)).where(
            Resource.owner_id == user_id, Resource.resource_type == resource_type, Resource.status != "destroyed"
        )
    )
    return result.scalar() or 0


async def _get_vmid_range(db: AsyncSession) -> tuple[int, int]:
    """Read VMID range from system settings."""
    start_result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "vmid_range_start")
    )
    end_result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "vmid_range_end")
    )
    start_setting = start_result.scalar_one_or_none()
    end_setting = end_result.scalar_one_or_none()
    start = int(start_setting.value) if start_setting else 1000
    end = int(end_setting.value) if end_setting else 999999
    return start, end


async def _get_user_resource(
    db: AsyncSession, user_id: uuid.UUID, resource_id: str, resource_type: str,
    min_group_perm: str = "read",
) -> Resource:
    rid = uuid.UUID(resource_id)
    # First try ownership
    query = select(Resource).where(Resource.id == rid, Resource.owner_id == user_id)
    if resource_type == "vm":
        query = query.where(Resource.resource_type.in_(["vm", "lxc"]))
    else:
        query = query.where(Resource.resource_type == resource_type)
    result = await db.execute(query)
    resource = result.scalar_one_or_none()

    # Fall back to group-level access
    if not resource:
        from app.services.group_access import check_group_access
        base = select(Resource).where(Resource.id == rid)
        if resource_type == "vm":
            base = base.where(Resource.resource_type.in_(["vm", "lxc"]))
        else:
            base = base.where(Resource.resource_type == resource_type)
        res2 = await db.execute(base)
        resource = res2.scalar_one_or_none()
        if resource and not await check_group_access(db, user_id, "resource", rid, min_group_perm):
            resource = None

    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    if resource.status == "destroyed":
        raise HTTPException(status_code=410, detail="Resource has been destroyed")
    # Touch last_accessed_at for lifecycle tracking
    resource.last_accessed_at = datetime.now(timezone.utc)
    await db.commit()
    return resource


async def _cleanup_resource_children(db: AsyncSession, resource_id: uuid.UUID) -> None:
    """Delete all child records that reference a resource via FK before resource deletion.

    This is the SINGLE cleanup function for resource deletion. Both _terminate_vm
    and delete_container MUST call this to avoid FK integrity errors.
    Any new model with FK to resources.id must be added here.
    """
    from app.models.models import (
        Alarm, Backup, BackupPlan, CustomMetric, GroupResourceShare,
        HealthCheck, IPReservation, LifecyclePolicy, ServiceEndpoint,
        Tag, TemplateRequest,
    )
    # Non-nullable FK tables - rows MUST be deleted or they block resource deletion
    for model in (
        Backup, BackupPlan, ServiceEndpoint, Alarm, HealthCheck,
        LifecyclePolicy, Tag, TemplateRequest,
    ):
        await db.execute(delete(model).where(model.resource_id == resource_id))
    # Nullable FK tables - delete to avoid orphans (could also SET NULL)
    for model in (IPReservation, CustomMetric, GroupResourceShare):
        await db.execute(delete(model).where(model.resource_id == resource_id))


async def _terminate_vm(db: AsyncSession, user: User, resource: Resource) -> dict:
    """Terminate (destroy) a VM or LXC - force stop if running then delete from Proxmox and DB."""

    # --- Protect PAWS-managed volumes ---
    # Volumes attached to this VM (status=attached) or parked as unused
    # (proxmox_owner_vmid matches) would be destroyed by PVE's delete_vm.
    vol_result = await db.execute(
        select(Volume).where(
            Volume.owner_id == user.id,
            Volume.resource_id == resource.id,
            Volume.status == "attached",
        )
    )
    attached_vols = list(vol_result.scalars().all())
    if attached_vols:
        names = ", ".join(v.name for v in attached_vols)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This instance has {len(attached_vols)} PAWS volume(s) attached: {names}. "
                "Detach or delete them from the Volumes page before destroying this instance, "
                "otherwise the volume data will be permanently lost."
            ),
        )

    # Volumes that were detached but still have unused entries on this VM
    if resource.proxmox_vmid:
        orphan_result = await db.execute(
            select(Volume).where(
                Volume.owner_id == user.id,
                Volume.proxmox_owner_vmid == resource.proxmox_vmid,
                Volume.status == "available",
            )
        )
        orphan_vols = list(orphan_result.scalars().all())
        if orphan_vols:
            # These disks exist as unused on this VM.  Try to remove the
            # unused config entries before deletion so PVE won't touch them.
            # If removal fails, block deletion to protect user data.
            try:
                config = proxmox_client.get_vm_config(
                    resource.proxmox_node, resource.proxmox_vmid
                )
                for ov in orphan_vols:
                    if ov.proxmox_volid:
                        unused_slot = None
                        for key, val in config.items():
                            if key.startswith("unused") and str(val).split(",")[0] == ov.proxmox_volid:
                                unused_slot = key
                                break
                        if unused_slot:
                            # Deleting unused entries DOES destroy the image,
                            # so we must NOT delete.  Instead, overwrite with a
                            # reference to 'none' so PVE drops it from config
                            # without touching the actual image.
                            #
                            # Fallback: if the disk was cross-node attached,
                            # the unused entry references a foreign volid that
                            # PVE might fail to delete anyway - still safe.
                            pass  # Leave it; PVE delete may warn but we can't safely remove
                    # Clear the owner reference so volumes page knows the
                    # backing VM is gone and the user can re-create if needed
                    ov.proxmox_owner_vmid = None
                    ov.proxmox_node = None
            except Exception:
                pass
            await db.flush()

    is_lxc = resource.resource_type == "lxc"
    try:
        if is_lxc:
            proxmox_client.stop_container(resource.proxmox_node, resource.proxmox_vmid)
        else:
            proxmox_client.stop_vm(resource.proxmox_node, resource.proxmox_vmid)
    except Exception:
        pass
    try:
        if is_lxc:
            proxmox_client.delete_container(resource.proxmox_node, resource.proxmox_vmid)
        else:
            proxmox_client.delete_vm(resource.proxmox_node, resource.proxmox_vmid)
    except Exception:
        pass

    old_vmid = resource.proxmox_vmid
    # Free VMID pool entry
    result = await db.execute(select(VMIDPool).where(VMIDPool.vmid == old_vmid))
    vmid_entry = result.scalar_one_or_none()
    if vmid_entry:
        await db.delete(vmid_entry)
    # Clean up all child records referencing this resource
    await _cleanup_resource_children(db, resource.id)
    # Delete the resource record entirely
    await db.delete(resource)
    await db.commit()
    await log_action(db, user.id, f"{resource.resource_type}_delete", resource.resource_type, details={"vmid": old_vmid})

    # Clean up Proxmox pool if user has no remaining VMs/LXCs
    try:
        await cleanup_user_pool(db, user)
    except Exception:
        pass

    return {"status": "destroyed"}


def _get_live_status(resource: Resource) -> dict:
    """Get live status from Proxmox, dispatching to correct API based on type.
    Falls back to cluster lookup if the stored node is stale (post-migration)."""
    node, vmid = resource.proxmox_node, resource.proxmox_vmid
    try:
        if resource.resource_type == "lxc":
            return proxmox_client.get_container_status(node, vmid)
        return proxmox_client.get_vm_status(node, vmid)
    except Exception:
        # Node may be stale after migration - look up current node
        actual_node = proxmox_client.find_vm_node(vmid)
        if actual_node and actual_node != node:
            resource.proxmox_node = actual_node
            if resource.resource_type == "lxc":
                return proxmox_client.get_container_status(actual_node, vmid)
            return proxmox_client.get_vm_status(actual_node, vmid)
        raise


async def _resolve_vpc_networking(
    db: AsyncSession, user: User, resource: Resource,
    vpc_id: str | None, network_mode: str = "private",
) -> None:
    """Resolve VPC and apply NIC bridge, bandwidth, and firewall rules post-creation.

    If vpc_id is provided, sets the NIC bridge to the VPC's VNet, auto-allocates
    a static IP from the subnet, and applies network mode firewall rules.
    The network_mode parameter is ignored - mode is derived from the VPC.
    If no vpc_id, sets NIC to vmbr0 with link_down=1 (disconnected).
    """
    import ipaddress as _ipaddr
    import uuid as _uuid
    from app.models.models import IPReservation, UserTier

    node = resource.proxmox_node
    vmid = resource.proxmox_vmid
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"

    # Resolve VPC
    vpc = None
    if vpc_id:
        result = await db.execute(
            select(VPC).where(VPC.id == _uuid.UUID(vpc_id), VPC.owner_id == user.id, VPC.status == "active")
        )
        vpc = result.scalar_one_or_none()

    if not vpc or not vpc.proxmox_vnet:
        # No VPC - set NIC to vmbr0 disconnected
        try:
            net0_val = _build_net0(vmtype, "vmbr0", link_down=True)
            if vmtype == "lxc":
                proxmox_client.set_container_config(node, vmid, net0=net0_val)
            else:
                proxmox_client.update_vm_config(node, vmid, net0=net0_val)
        except Exception:
            logger.warning("Failed to set disconnected NIC for %s/%s", node, vmid, exc_info=True)
        return

    # Derive network mode from VPC
    effective_mode = vpc.network_mode or "private"

    # Get first subnet for IP allocation
    subnet_result = await db.execute(
        select(Subnet).where(Subnet.vpc_id == vpc.id, Subnet.status == "active")
        .options(selectinload(Subnet.ip_reservations))
        .limit(1)
    )
    subnet = subnet_result.scalar_one_or_none()

    # Get bandwidth limit from tier
    tier_result = await db.execute(
        select(UserTier).join(User, User.tier_id == UserTier.id).where(User.id == user.id)
    )
    tier = tier_result.scalar_one_or_none()
    bw = FirewallProfileService.get_effective_bandwidth(
        tier.bandwidth_limit_mbps if tier else None, None
    )

    # Auto-allocate a static IP from the subnet (DHCP not supported on EVPN/VXLAN)
    ip_str = None
    prefix_len = None
    gateway = None
    if subnet:
        try:
            network = _ipaddr.ip_network(subnet.cidr, strict=False)
            prefix_len = network.prefixlen
            gateway = subnet.gateway or str(list(network.hosts())[0])
            used_ips = {r.ip_address for r in subnet.ip_reservations}
            for host in list(network.hosts())[1:]:
                if str(host) not in used_ips:
                    ip_str = str(host)
                    break
            if ip_str:
                db.add(IPReservation(
                    subnet_id=subnet.id, ip_address=ip_str, resource_id=resource.id,
                    label=resource.display_name, is_gateway=False, owner_id=user.id,
                ))
        except Exception:
            logger.warning("Failed to allocate IP for %s/%s", node, vmid, exc_info=True)

    # Build and apply NIC config via unified helpers
    bridge = vpc.proxmox_vnet
    try:
        net0_val = _build_net0(
            vmtype, bridge,
            ip=ip_str, prefix_len=prefix_len, gateway=gateway,
            rate=bw,
        )
        dns = (subnet.dns_server or "1.1.1.1") if subnet else "1.1.1.1"
        _apply_nic(
            node, vmid, vmtype, net0_val,
            ip=ip_str, prefix_len=prefix_len, gateway=gateway,
            dns_server=dns,
        )
    except Exception:
        logger.warning("Failed to set NIC bridge for %s/%s", node, vmid, exc_info=True)
        return

    # Store vpc_id and subnet info on resource
    specs = json.loads(resource.specs) if resource.specs else {}
    specs["vpc_id"] = str(vpc.id)
    if ip_str:
        specs["ip_address"] = ip_str
    if subnet:
        specs["subnet_cidr"] = subnet.cidr
    resource.specs = json.dumps(specs)
    resource.network_mode = effective_mode

    # Apply firewall mode rules
    if subnet:
        try:
            lan_ranges = await FirewallProfileService.get_lan_ranges_async(db)
            upstream_ips = await FirewallProfileService.get_upstream_ips_async(db)
            FirewallProfileService.enable_firewall(node, vmid, vmtype)
            FirewallProfileService.apply_network_mode(
                node, vmid, vmtype, effective_mode, subnet.cidr,
                lan_ranges=lan_ranges, upstream_ips=upstream_ips,
            )
        except Exception:
            logger.warning("Failed to apply firewall mode for %s/%s", node, vmid, exc_info=True)

    # Auto-attach managed security group for published networks
    if effective_mode == "published" and vpc.security_group_id:
        from app.models.models import ResourceSecurityGroup
        existing_link = await db.execute(
            select(ResourceSecurityGroup).where(
                ResourceSecurityGroup.resource_id == resource.id,
                ResourceSecurityGroup.security_group_id == vpc.security_group_id,
            )
        )
        if not existing_link.scalar_one_or_none():
            db.add(ResourceSecurityGroup(
                resource_id=resource.id, security_group_id=vpc.security_group_id,
            ))


def _do_action(resource: Resource, action: str, **kwargs) -> str:
    """Execute a lifecycle action on a VM or LXC, returning the UPID."""
    node, vmid = resource.proxmox_node, resource.proxmox_vmid
    is_lxc = resource.resource_type == "lxc"

    # Enforce network safety before start/reboot
    if action in ("start", "reboot"):
        _enforce_network_safety(resource)

    actions_vm = {
        "start": proxmox_client.start_vm,
        "stop": proxmox_client.stop_vm,
        "shutdown": proxmox_client.shutdown_vm,
        "reboot": proxmox_client.reboot_vm,
        "resume": proxmox_client.resume_vm,
    }
    actions_lxc = {
        "start": proxmox_client.start_container,
        "stop": proxmox_client.stop_container,
        "shutdown": proxmox_client.shutdown_container,
        "reboot": lambda n, v: proxmox_client.api.nodes(n).lxc(v).status.reboot.post(),
        "resume": lambda n, v: proxmox_client.api.nodes(n).lxc(v).status.resume.post(),
    }
    fn = (actions_lxc if is_lxc else actions_vm).get(action)
    if not fn:
        raise ValueError(f"Action '{action}' not supported for {resource.resource_type}")
    return fn(node, vmid)


def _enforce_network_safety(resource: Resource) -> None:
    """Block start/reboot if net0 is on vmbr0 without link_down (disconnected).

    Instances MUST either be on their own SDN VNet bridge or have their NIC
    disconnected (link_down=1) to prevent direct access to the host network.
    """
    node, vmid = resource.proxmox_node, resource.proxmox_vmid
    is_lxc = resource.resource_type == "lxc"
    try:
        if is_lxc:
            config = proxmox_client.get_container_config(node, vmid)
        else:
            config = proxmox_client.get_vm_config(node, vmid)
        net0 = str(config.get("net0", ""))
        if not net0:
            return
        # Parse net0 key=value pairs
        parts = {}
        for segment in net0.split(","):
            if "=" in segment:
                k, v = segment.split("=", 1)
                parts[k.strip()] = v.strip()
        bridge = parts.get("bridge", "")
        link_down = parts.get("link_down", "0")
        # Allow if not on vmbr0 (already on SDN VNet)
        if bridge != "vmbr0":
            return
        # On vmbr0 - only allow if disconnected
        if link_down == "1":
            return
        raise ValueError(
            "Network safety: this instance is connected to vmbr0 without a VPC. "
            "Assign a VPC network before starting, or the NIC must be disconnected."
        )
    except ValueError:
        raise
    except Exception as e:
        logger.warning("Network safety check failed for %s/%s: %s", node, vmid, e)

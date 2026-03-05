"""Proxmox VE API client service layer.

All Proxmox interactions go through this service - never call proxmoxer directly from routes.
Uses scoped API tokens for authentication.
"""

import logging
from typing import Any

from proxmoxer import ProxmoxAPI

from app.core.config import settings

logger = logging.getLogger(__name__)


class ProxmoxClient:
    _instance: "ProxmoxClient | None" = None
    _api: ProxmoxAPI | None = None

    def __new__(cls) -> "ProxmoxClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _connect(self) -> ProxmoxAPI:
        if self._api is None:
            if not settings.proxmox_host:
                raise ConnectionError("Proxmox host not configured (set PAWS_PROXMOX_HOST)")

            token_id = settings.proxmox_token_id
            token_secret = settings.proxmox_token_secret
            host = settings.proxmox_host.replace("https://", "").replace("http://", "").split(":")[0].rstrip("/")
            port = settings.proxmox_port

            self._api = ProxmoxAPI(
                host,
                port=port,
                user=token_id.split("!")[0],
                token_name=token_id.split("!")[-1],
                token_value=token_secret,
                verify_ssl=settings.proxmox_verify_ssl,
                timeout=30,
            )
            logger.info("Connected to Proxmox at %s:%d", host, port)
        return self._api

    @property
    def api(self) -> ProxmoxAPI:
        return self._connect()

    # --- Cluster / Node Operations ---

    def get_nodes(self) -> list[dict[str, Any]]:
        return self.api.nodes.get()

    def get_node_status(self, node: str) -> dict[str, Any]:
        return self.api.nodes(node).status.get()

    def get_cluster_status(self) -> list[dict[str, Any]]:
        return self.api.cluster.status.get()

    def get_cluster_resources(self, resource_type: str | None = None) -> list[dict[str, Any]]:
        params = {}
        if resource_type:
            params["type"] = resource_type
        return self.api.cluster.resources.get(**params)

    # --- VM Operations ---

    def create_vm(self, node: str, vmid: int, **kwargs: Any) -> str:
        """Clone or create a VM. Returns the UPID of the task."""
        return self.api.nodes(node).qemu.post(vmid=vmid, **kwargs)

    def clone_vm(self, node: str, source_vmid: int, new_vmid: int, **kwargs: Any) -> str:
        return self.api.nodes(node).qemu(source_vmid).clone.post(newid=new_vmid, **kwargs)

    def clone_container(self, node: str, source_vmid: int, new_vmid: int, **kwargs: Any) -> str:
        return self.api.nodes(node).lxc(source_vmid).clone.post(newid=new_vmid, **kwargs)

    def migrate_vm(self, node: str, vmid: int, target: str, online: bool = False) -> str:
        """Migrate a VM to another node. Returns UPID."""
        return self.api.nodes(node).qemu(vmid).migrate.post(target=target, online=int(online))

    def migrate_container(self, node: str, vmid: int, target: str, online: bool = False) -> str:
        """Migrate a container to another node. Returns UPID."""
        return self.api.nodes(node).lxc(vmid).migrate.post(target=target, online=int(online))

    def find_vm_node(self, vmid: int) -> str | None:
        """Find which node a VMID lives on by checking cluster resources."""
        try:
            resources = self.get_cluster_resources()
            for r in resources:
                if r.get("vmid") == vmid:
                    return r.get("node")
        except Exception:
            pass
        return None

    def get_resource_type(self, vmid: int) -> str | None:
        """Get the type ('qemu' or 'lxc') of a VMID from cluster resources."""
        try:
            resources = self.get_cluster_resources()
            for r in resources:
                if r.get("vmid") == vmid:
                    return r.get("type")
        except Exception:
            pass
        return None

    def is_storage_shared(self, storage_name: str) -> bool:
        """Check if a storage pool is shared across the cluster."""
        try:
            storages = self.api.storage.get()
            for s in storages:
                if s.get("storage") == storage_name:
                    return bool(s.get("shared", 0))
        except Exception:
            pass
        return False

    def get_vm_disk_storage(self, node: str, vmid: int) -> str | None:
        """Get the storage pool of a VM's primary disk."""
        try:
            config = self.get_vm_config(node, vmid)
            for key in ("scsi0", "virtio0", "ide0", "sata0"):
                val = config.get(key, "")
                if val and ":" in val:
                    return val.split(":")[0]
        except Exception:
            pass
        return None

    def get_vm_status(self, node: str, vmid: int) -> dict[str, Any]:
        return self.api.nodes(node).qemu(vmid).status.current.get()

    def get_vm_config(self, node: str, vmid: int) -> dict[str, Any]:
        return self.api.nodes(node).qemu(vmid).config.get()

    def start_vm(self, node: str, vmid: int) -> str:
        return self.api.nodes(node).qemu(vmid).status.start.post()

    def stop_vm(self, node: str, vmid: int) -> str:
        return self.api.nodes(node).qemu(vmid).status.stop.post()

    def shutdown_vm(self, node: str, vmid: int) -> str:
        return self.api.nodes(node).qemu(vmid).status.shutdown.post()

    def reboot_vm(self, node: str, vmid: int) -> str:
        return self.api.nodes(node).qemu(vmid).status.reboot.post()

    def suspend_vm(self, node: str, vmid: int, to_disk: bool = False) -> str:
        """Suspend (pause) or hibernate (to disk) a VM."""
        return self.api.nodes(node).qemu(vmid).status.suspend.post(todisk=int(to_disk))

    def resume_vm(self, node: str, vmid: int) -> str:
        return self.api.nodes(node).qemu(vmid).status.resume.post()

    def delete_vm(self, node: str, vmid: int) -> str:
        return self.api.nodes(node).qemu(vmid).delete()

    def resize_vm_disk(self, node: str, vmid: int, disk: str, size: str) -> None:
        self.api.nodes(node).qemu(vmid).resize.put(disk=disk, size=size)

    def update_vm_config(self, node: str, vmid: int, **kwargs: Any) -> None:
        self.api.nodes(node).qemu(vmid).config.put(**kwargs)

    def resize_vm(self, node: str, vmid: int, cores: int, memory_mb: int) -> None:
        self.api.nodes(node).qemu(vmid).config.put(cores=cores, memory=memory_mb)

    # --- LXC Operations ---

    def create_container(self, node: str, vmid: int, **kwargs: Any) -> str:
        return self.api.nodes(node).lxc.post(vmid=vmid, **kwargs)

    def get_container_status(self, node: str, vmid: int) -> dict[str, Any]:
        return self.api.nodes(node).lxc(vmid).status.current.get()

    def start_container(self, node: str, vmid: int) -> str:
        return self.api.nodes(node).lxc(vmid).status.start.post()

    def stop_container(self, node: str, vmid: int) -> str:
        return self.api.nodes(node).lxc(vmid).status.stop.post()

    def shutdown_container(self, node: str, vmid: int) -> str:
        return self.api.nodes(node).lxc(vmid).status.shutdown.post()

    def delete_container(self, node: str, vmid: int) -> str:
        return self.api.nodes(node).lxc(vmid).delete()

    def get_container_config(self, node: str, vmid: int) -> dict[str, Any]:
        return self.api.nodes(node).lxc(vmid).config.get()

    def set_container_config(self, node: str, vmid: int, **kwargs: Any) -> None:
        self.api.nodes(node).lxc(vmid).config.put(**kwargs)

    def get_container_disk_storage(self, node: str, vmid: int) -> str | None:
        """Get the storage pool of a container's rootfs."""
        try:
            config = self.get_container_config(node, vmid)
            rootfs = config.get("rootfs", "")
            if rootfs and ":" in rootfs:
                return rootfs.split(":")[0]
        except Exception:
            pass
        return None

    # --- Storage ---

    def get_storage_list(self, node: str | None = None) -> list[dict[str, Any]]:
        if node:
            return self.api.nodes(node).storage.get()
        return self.api.storage.get()

    def get_storage_content(self, node: str, storage: str) -> list[dict[str, Any]]:
        return self.api.nodes(node).storage(storage).content.get()

    # --- Templates ---

    def get_vm_templates(self) -> list[dict[str, Any]]:
        """Get all VM templates across the cluster."""
        resources = self.get_cluster_resources("vm")
        return [r for r in resources if r.get("template", 0) == 1]

    def get_container_templates(self, node: str, storage: str) -> list[dict[str, Any]]:
        content = self.get_storage_content(node, storage)
        return [c for c in content if c.get("content") == "vztmpl"]

    # --- Snapshots / Backups ---

    def create_snapshot(self, node: str, vmid: int, snapname: str, vmtype: str = "qemu", **kwargs: Any) -> str:
        if vmtype == "lxc":
            return self.api.nodes(node).lxc(vmid).snapshot.post(snapname=snapname, **kwargs)
        return self.api.nodes(node).qemu(vmid).snapshot.post(snapname=snapname, **kwargs)

    def list_snapshots(self, node: str, vmid: int, vmtype: str = "qemu") -> list[dict[str, Any]]:
        if vmtype == "lxc":
            return self.api.nodes(node).lxc(vmid).snapshot.get()
        return self.api.nodes(node).qemu(vmid).snapshot.get()

    def delete_snapshot(self, node: str, vmid: int, snapname: str, vmtype: str = "qemu") -> str:
        if vmtype == "lxc":
            return self.api.nodes(node).lxc(vmid).snapshot(snapname).delete()
        return self.api.nodes(node).qemu(vmid).snapshot(snapname).delete()

    def rollback_snapshot(self, node: str, vmid: int, snapname: str, vmtype: str = "qemu") -> str:
        if vmtype == "lxc":
            return self.api.nodes(node).lxc(vmid).snapshot(snapname).rollback.post()
        return self.api.nodes(node).qemu(vmid).snapshot(snapname).rollback.post()

    # --- Task Tracking ---

    def get_task_status(self, node: str, upid: str) -> dict[str, Any]:
        return self.api.nodes(node).tasks(upid).status.get()

    def wait_for_task(self, node: str, upid: str, timeout: int = 120, interval: int = 2) -> dict[str, Any]:
        """Poll a task until it completes or times out."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.get_task_status(node, upid)
            if status.get("status") == "stopped":
                return status
            time.sleep(interval)
        raise TimeoutError(f"Task {upid} did not complete within {timeout}s")

    def get_node_tasks(self, node: str, vmid: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Get task list for a node, optionally filtered by VMID."""
        params: dict[str, Any] = {"limit": limit}
        if vmid:
            params["vmid"] = vmid
        return self.api.nodes(node).tasks.get(**params)

    def get_rrd_data(self, node: str, vmid: int, vmtype: str = "qemu", timeframe: str = "hour") -> list[dict[str, Any]]:
        if vmtype == "lxc":
            return self.api.nodes(node).lxc(vmid).rrddata.get(timeframe=timeframe)
        return self.api.nodes(node).qemu(vmid).rrddata.get(timeframe=timeframe)

    # --- Networking (SDN) ---

    def get_sdn_zones(self) -> list[dict[str, Any]]:
        return self.api.cluster.sdn.zones.get()

    def get_sdn_vnets(self) -> list[dict[str, Any]]:
        return self.api.cluster.sdn.vnets.get()

    def create_sdn_vnet(self, vnet: str, zone: str, **kwargs: Any) -> None:
        self.api.cluster.sdn.vnets.post(vnet=vnet, zone=zone, **kwargs)

    def delete_sdn_vnet(self, vnet: str) -> None:
        self.api.cluster.sdn.vnets(vnet).delete()

    # --- Console ---

    def get_vnc_ticket(self, node: str, vmid: int, vmtype: str = "qemu") -> dict[str, Any]:
        if vmtype == "lxc":
            return self.api.nodes(node).lxc(vmid).vncproxy.post(websocket=1)
        return self.api.nodes(node).qemu(vmid).vncproxy.post(websocket=1)

    def get_terminal_proxy(self, node: str, vmid: int, vmtype: str = "qemu") -> dict[str, Any]:
        """Get a terminal (serial) proxy ticket for xterm.js console."""
        if vmtype == "lxc":
            return self.api.nodes(node).lxc(vmid).termproxy.post()
        return self.api.nodes(node).qemu(vmid).termproxy.post()

    def get_spice_ticket(self, node: str, vmid: int, vmtype: str = "qemu") -> dict[str, Any]:
        if vmtype == "lxc":
            return self.api.nodes(node).lxc(vmid).spiceproxy.post()
        return self.api.nodes(node).qemu(vmid).spiceproxy.post()

    # --- Migration/Export ---

    def create_backup(self, node: str, vmid: int, **kwargs: Any) -> str:
        """Create a vzdump backup of a VM/container."""
        return self.api.nodes(node).vzdump.post(vmid=vmid, **kwargs)

    def convert_to_template(self, node: str, vmid: int) -> None:
        """Convert a VM to a template."""
        self.api.nodes(node).qemu(vmid).template.post()

    def get_agent_info(self, node: str, vmid: int) -> dict[str, Any]:
        """Get QEMU guest agent info."""
        return self.api.nodes(node).qemu(vmid).agent.get(command="info")


proxmox_client = ProxmoxClient()

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
    _session_ticket: str | None = None
    _session_user: str | None = None

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

    def get_session_ticket(self) -> tuple[str, str]:
        """Get a PVE session ticket using username+password.

        Required for xterm.js terminal auth (termproxy does not support API tokens).
        Returns (username, ticket) tuple.
        """
        import requests

        if not settings.proxmox_password:
            raise ConnectionError("PAWS_PROXMOX_PASSWORD required for terminal console access")

        host = settings.proxmox_host.replace("https://", "").replace("http://", "").split(":")[0].rstrip("/")
        port = settings.proxmox_port
        user = settings.proxmox_token_id.split("!")[0]

        resp = requests.post(
            f"https://{host}:{port}/api2/json/access/ticket",
            data={"username": user, "password": settings.proxmox_password},
            verify=settings.proxmox_verify_ssl,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        self._session_ticket = data["ticket"]
        self._session_user = data["username"]
        return (data["username"], data["ticket"])

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

    def set_vm_description(self, node: str, vmid: int, description: str) -> None:
        """Set the description/notes field on a VM or LXC."""
        try:
            self.api.nodes(node).qemu(vmid).config.put(description=description)
        except Exception:
            self.api.nodes(node).lxc(vmid).config.put(description=description)

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

    def move_vm_disk(
        self,
        node: str,
        vmid: int,
        disk: str,
        target_vmid: int | None = None,
        target_disk: str | None = None,
        storage: str | None = None,
    ) -> str:
        """Move a VM disk to another storage or another VM."""
        params: dict[str, Any] = {"disk": disk}
        if target_vmid is not None:
            params["target-vmid"] = target_vmid
        if target_disk is not None:
            params["target-disk"] = target_disk
        if storage is not None:
            params["storage"] = storage
        return self.api.nodes(node).qemu(vmid).move_disk.post(**params)

    def allocate_storage_volume(self, node: str, storage: str, vmid: int, size: str, fmt: str = "raw") -> str:
        """Allocate a new volume on storage. Returns the volume identifier."""
        return self.api.nodes(node).storage(storage).content.post(vmid=vmid, size=size, format=fmt)

    def update_vm_config(self, node: str, vmid: int, **kwargs: Any) -> None:
        self.api.nodes(node).qemu(vmid).config.put(**kwargs)

    def regenerate_cloudinit(self, node: str, vmid: int) -> None:
        """Regenerate the cloud-init ISO so pending config changes take effect on next boot."""
        self.api.nodes(node).qemu(vmid).cloudinit.put()

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

    def get_storage_config(self, storage: str) -> dict[str, Any]:
        """Get configuration of a specific storage."""
        return self.api.storage(storage).get()

    def create_pbs_storage(
        self,
        name: str,
        server: str,
        datastore: str,
        namespace: str,
        fingerprint: str,
        username: str,
        password: str,
        port: int = 8007,
    ) -> None:
        """Create a PVE storage config pointing to a PBS namespace."""
        self.api.storage.post(
            storage=name,
            type="pbs",
            server=server,
            port=port,
            datastore=datastore,
            namespace=namespace,
            content="backup",
            username=username,
            password=password,
            fingerprint=fingerprint,
        )

    def storage_exists(self, name: str) -> bool:
        """Check if a PVE storage config exists."""
        try:
            self.api.storage(name).get()
            return True
        except Exception:
            return False

    def delete_storage_content(self, node: str, storage: str, volid: str) -> str:
        """Delete a volume (backup file) from storage."""
        return self.api.nodes(node).storage(storage).content(volid).delete()

    def list_backup_files(self, node: str, storage: str, volid: str, filepath: str = "/") -> list[dict[str, Any]]:
        """List files inside a backup via PVE's file-restore API."""
        import base64

        fp_b64 = base64.b64encode(filepath.encode()).decode()
        result = (
            self.api.nodes(node)
            .storage(storage)("file-restore")("list")
            .get(
                volume=volid,
                filepath=fp_b64,
            )
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return [result] if result else []

    def download_backup_file(self, node: str, storage: str, volid: str, filepath: str) -> Any:
        """Download a file from a backup via PVE's file-restore API. Returns raw response."""
        import base64

        fp_b64 = base64.b64encode(filepath.encode()).decode()
        return (
            self.api.nodes(node)
            .storage(storage)("file-restore")("download")
            .get(
                volume=volid,
                filepath=fp_b64,
            )
        )

    def restore_vm_backup(
        self,
        node: str,
        vmid: int,
        archive: str,
        storage: str | None = None,
    ) -> str:
        """Restore a VM from a backup archive (qmrestore)."""
        kwargs: dict[str, Any] = {"vmid": vmid, "archive": archive, "force": 1}
        if storage:
            kwargs["storage"] = storage
        return self.api.nodes(node).qemu.post(**kwargs)

    def restore_ct_backup(
        self,
        node: str,
        vmid: int,
        archive: str,
        storage: str | None = None,
    ) -> str:
        """Restore a container from a backup archive (pct restore)."""
        kwargs: dict[str, Any] = {"vmid": vmid, "ostemplate": archive, "force": 1, "restore": 1}
        if storage:
            kwargs["storage"] = storage
        return self.api.nodes(node).lxc.post(**kwargs)

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

    def get_task_log(self, node: str, upid: str, limit: int = 1000, start: int = 0) -> list[dict[str, Any]]:
        """Get log lines for a specific task."""
        return self.api.nodes(node).tasks(upid).log.get(limit=limit, start=start)

    def get_rrd_data(self, node: str, vmid: int, vmtype: str = "qemu", timeframe: str = "hour") -> list[dict[str, Any]]:
        if vmtype == "lxc":
            return self.api.nodes(node).lxc(vmid).rrddata.get(timeframe=timeframe)
        return self.api.nodes(node).qemu(vmid).rrddata.get(timeframe=timeframe)

    # --- Networking (SDN) ---

    def get_sdn_zones(self) -> list[dict[str, Any]]:
        return self.api.cluster.sdn.zones.get()

    def get_sdn_vnets(self) -> list[dict[str, Any]]:
        return self.api.cluster.sdn.vnets.get()

    def get_sdn_vnet(self, vnet: str) -> dict[str, Any]:
        return self.api.cluster.sdn.vnets(vnet).get()

    def create_sdn_vnet(self, vnet: str, zone: str, **kwargs: Any) -> None:
        self.api.cluster.sdn.vnets.post(vnet=vnet, zone=zone, **kwargs)

    def delete_sdn_vnet(self, vnet: str) -> None:
        self.api.cluster.sdn.vnets(vnet).delete()

    def get_sdn_subnets(self, vnet: str) -> list[dict[str, Any]]:
        return self.api.cluster.sdn.vnets(vnet).subnets.get()

    def create_sdn_subnet(self, vnet: str, subnet: str, gateway: str, snat: bool = True, **kwargs: Any) -> None:
        self.api.cluster.sdn.vnets(vnet).subnets.post(
            subnet=subnet, gateway=gateway, snat=1 if snat else 0, type="subnet", **kwargs
        )

    def delete_sdn_subnet(self, vnet: str, subnet_id: str) -> None:
        self.api.cluster.sdn.vnets(vnet).subnets(subnet_id).delete()

    def apply_sdn(self) -> None:
        self.api.cluster.sdn.put()

    # --- Firewall (VM/Container level) ---

    def get_vm_firewall_options(self, node: str, vmid: int) -> dict[str, Any]:
        return self.api.nodes(node).qemu(vmid).firewall.options.get()

    def set_vm_firewall_options(self, node: str, vmid: int, **kwargs: Any) -> None:
        self.api.nodes(node).qemu(vmid).firewall.options.put(**kwargs)

    def get_vm_firewall_rules(self, node: str, vmid: int) -> list[dict[str, Any]]:
        return self.api.nodes(node).qemu(vmid).firewall.rules.get()

    def create_vm_firewall_rule(self, node: str, vmid: int, **kwargs: Any) -> None:
        self.api.nodes(node).qemu(vmid).firewall.rules.post(**kwargs)

    def update_vm_firewall_rule(self, node: str, vmid: int, pos: int, **kwargs: Any) -> None:
        self.api.nodes(node).qemu(vmid).firewall.rules(pos).put(**kwargs)

    def delete_vm_firewall_rule(self, node: str, vmid: int, pos: int) -> None:
        self.api.nodes(node).qemu(vmid).firewall.rules(pos).delete()

    def get_container_firewall_options(self, node: str, vmid: int) -> dict[str, Any]:
        return self.api.nodes(node).lxc(vmid).firewall.options.get()

    def set_container_firewall_options(self, node: str, vmid: int, **kwargs: Any) -> None:
        self.api.nodes(node).lxc(vmid).firewall.options.put(**kwargs)

    def get_container_firewall_rules(self, node: str, vmid: int) -> list[dict[str, Any]]:
        return self.api.nodes(node).lxc(vmid).firewall.rules.get()

    def create_container_firewall_rule(self, node: str, vmid: int, **kwargs: Any) -> None:
        self.api.nodes(node).lxc(vmid).firewall.rules.post(**kwargs)

    def update_container_firewall_rule(self, node: str, vmid: int, pos: int, **kwargs: Any) -> None:
        self.api.nodes(node).lxc(vmid).firewall.rules(pos).put(**kwargs)

    def delete_container_firewall_rule(self, node: str, vmid: int, pos: int) -> None:
        self.api.nodes(node).lxc(vmid).firewall.rules(pos).delete()

    def get_firewall_rules(self, node: str, vmid: int, vmtype: str = "qemu") -> list[dict[str, Any]]:
        if vmtype == "lxc":
            return self.get_container_firewall_rules(node, vmid)
        return self.get_vm_firewall_rules(node, vmid)

    def create_firewall_rule(self, node: str, vmid: int, vmtype: str = "qemu", **kwargs: Any) -> None:
        if vmtype == "lxc":
            self.create_container_firewall_rule(node, vmid, **kwargs)
        else:
            self.create_vm_firewall_rule(node, vmid, **kwargs)

    def delete_firewall_rule(self, node: str, vmid: int, pos: int, vmtype: str = "qemu") -> None:
        if vmtype == "lxc":
            self.delete_container_firewall_rule(node, vmid, pos)
        else:
            self.delete_vm_firewall_rule(node, vmid, pos)

    def set_firewall_options(self, node: str, vmid: int, vmtype: str = "qemu", **kwargs: Any) -> None:
        if vmtype == "lxc":
            self.set_container_firewall_options(node, vmid, **kwargs)
        else:
            self.set_vm_firewall_options(node, vmid, **kwargs)

    def clear_firewall_rules_by_comment(self, node: str, vmid: int, vmtype: str, comment_prefix: str) -> int:
        """Delete all firewall rules whose comment starts with the given prefix.
        Returns the number of rules deleted."""
        rules = self.get_firewall_rules(node, vmid, vmtype)
        positions_to_delete = sorted(
            [r["pos"] for r in rules if r.get("comment", "").startswith(comment_prefix)],
            reverse=True,
        )
        for pos in positions_to_delete:
            self.delete_firewall_rule(node, vmid, pos, vmtype)
        return len(positions_to_delete)

    # --- Guest Agent ---

    def get_agent_network_interfaces(self, node: str, vmid: int) -> list[dict[str, Any]]:
        """Get network interfaces reported by the QEMU guest agent."""
        try:
            result = self.api.nodes(node).qemu(vmid).agent("network-get-interfaces").get()
            return result.get("result", [])
        except Exception:
            return []

    def agent_fsfreeze(self, node: str, vmid: int, freeze: bool = True) -> None:
        """Freeze or thaw guest filesystems via the guest agent."""
        cmd = "fsfreeze-freeze" if freeze else "fsfreeze-thaw"
        self.api.nodes(node).qemu(vmid).agent(cmd).post()

    def is_agent_running(self, node: str, vmid: int) -> bool:
        """Check if the QEMU guest agent is responding."""
        try:
            self.api.nodes(node).qemu(vmid).agent.get(command="ping")
            return True
        except Exception:
            return False

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

    # --- High Availability ---

    def get_ha_groups(self) -> list[dict[str, Any]]:
        """Get all HA groups from the cluster."""
        return self.api.cluster.ha.groups.get()

    def get_ha_group(self, group_name: str) -> dict[str, Any]:
        """Get details of a specific HA group."""
        return self.api.cluster.ha.groups(group_name).get()

    def create_ha_group(self, group_name: str, nodes: str, **kwargs: Any) -> None:
        """Create an HA group. nodes is comma-separated e.g. 'node1,node2'."""
        self.api.cluster.ha.groups.post(group=group_name, nodes=nodes, **kwargs)

    def update_ha_group(self, group_name: str, **kwargs: Any) -> None:
        """Update an HA group."""
        self.api.cluster.ha.groups(group_name).put(**kwargs)

    def delete_ha_group(self, group_name: str) -> None:
        """Delete an HA group."""
        self.api.cluster.ha.groups(group_name).delete()

    def get_ha_resources(self) -> list[dict[str, Any]]:
        """Get all HA-managed resources."""
        return self.api.cluster.ha.resources.get()

    def get_ha_resource(self, sid: str) -> dict[str, Any]:
        """Get HA status for a specific resource. sid format: 'vm:VMID' or 'ct:VMID'."""
        return self.api.cluster.ha.resources(sid).get()

    def add_ha_resource(self, sid: str, group: str | None = None, **kwargs: Any) -> None:
        """Add a resource to HA management. sid format: 'vm:VMID' or 'ct:VMID'."""
        params: dict[str, Any] = {"sid": sid}
        if group:
            params["group"] = group
        params.update(kwargs)
        self.api.cluster.ha.resources.post(**params)

    def remove_ha_resource(self, sid: str) -> None:
        """Remove a resource from HA management."""
        self.api.cluster.ha.resources(sid).delete()

    def get_ha_status(self) -> list[dict[str, Any]]:
        """Get HA manager status (current HA resource states)."""
        return self.api.cluster.ha.status.current.get()

    def get_ha_rules(self) -> list[dict[str, Any]]:
        """Get HA rules (PVE 8.2+ replacement for HA groups)."""
        return self.api.cluster.ha.rules.get()

    # --- Pool Management ---

    def create_pool(self, poolid: str, comment: str = "") -> None:
        """Create a resource pool on the cluster."""
        self.api.pools.post(poolid=poolid, comment=comment)

    def delete_pool(self, poolid: str) -> None:
        """Delete an empty resource pool."""
        self.api.pools(poolid).delete()

    def get_pool(self, poolid: str) -> dict[str, Any]:
        """Get pool info including members."""
        return self.api.pools(poolid).get()

    def list_pools(self) -> list[dict[str, Any]]:
        """List all resource pools."""
        return self.api.pools.get()

    def pool_exists(self, poolid: str) -> bool:
        """Check if a pool exists."""
        try:
            self.api.pools(poolid).get()
            return True
        except Exception:
            return False

    def add_to_pool(self, poolid: str, vmid: int) -> None:
        """Add a VM/container to a pool."""
        self.api.pools(poolid).put(vms=str(vmid))

    def remove_from_pool(self, poolid: str, vmid: int) -> None:
        """Remove a VM/container from a pool."""
        self.api.pools(poolid).put(vms=str(vmid), delete=1)

    def get_pool_name_for_user(self, username: str) -> str:
        """Get the standard pool name for a PAWS user."""
        safe = username.lower().replace(" ", "-")[:30]
        return f"paws-{safe}"


proxmox_client = ProxmoxClient()

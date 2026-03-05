"""Node inventory and placement engine."""

from typing import Any

from app.services.proxmox_client import proxmox_client


def get_node_resources() -> list[dict[str, Any]]:
    """Get all nodes with their resource info."""
    nodes = proxmox_client.get_nodes()
    result = []
    for node in nodes:
        result.append(
            {
                "name": node.get("node"),
                "status": node.get("status"),
                "cpu_usage": node.get("cpu", 0),
                "cpu_count": node.get("maxcpu", 0),
                "mem_used": node.get("mem", 0),
                "mem_total": node.get("maxmem", 0),
                "disk_used": node.get("disk", 0),
                "disk_total": node.get("maxdisk", 0),
                "uptime": node.get("uptime", 0),
            }
        )
    return result


def select_node(strategy: str = "least-loaded") -> str:
    """Select a node for VM/container placement based on strategy."""
    nodes = [n for n in get_node_resources() if n["status"] == "online"]
    if not nodes:
        raise RuntimeError("No online nodes available in the cluster")

    if strategy == "least-loaded":
        return min(nodes, key=lambda n: n["cpu_usage"])["name"]
    elif strategy == "pack-dense":
        return max(nodes, key=lambda n: n["cpu_usage"])["name"]
    elif strategy == "round-robin":
        resources = proxmox_client.get_cluster_resources("vm")
        vm_counts: dict[str, int] = {}
        for r in resources:
            n = r.get("node", "")
            vm_counts[n] = vm_counts.get(n, 0) + 1
        return min(nodes, key=lambda n: vm_counts.get(n["name"], 0))["name"]
    else:
        return nodes[0]["name"]


def get_proxmox_vmids() -> set[int]:
    """Get all VMIDs currently in use on the Proxmox cluster."""
    try:
        resources = proxmox_client.get_cluster_resources()
        return {r["vmid"] for r in resources if "vmid" in r}
    except Exception:
        return set()


def get_next_vmid(existing_vmids: set[int], start: int = 100, end: int = 999999) -> int:
    """Find next available VMID not in the existing set or on the cluster."""
    cluster_vmids = get_proxmox_vmids()
    all_used = existing_vmids | cluster_vmids
    for vmid in range(start, end + 1):
        if vmid not in all_used:
            return vmid
    raise RuntimeError("No available VMIDs in range")

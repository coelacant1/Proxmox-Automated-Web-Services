"""SDN (Software-Defined Networking) service for Proxmox VPC networking.

Manages VXLAN zones, VNets, and subnet configurations to provide
per-user/per-VPC isolated networking via Proxmox SDN.
"""

import logging
from typing import Any

from app.services.proxmox_client import proxmox_client

logger = logging.getLogger(__name__)

# VXLAN tag range for tenant isolation (10000-16777215)
VXLAN_TAG_MIN = 10000
VXLAN_TAG_MAX = 16777215

# Naming conventions
ZONE_PREFIX = "paws"
VNET_PREFIX = "pv"


class SDNService:
    """Manages Proxmox SDN zones and VNets for VPC networking."""

    def get_zones(self) -> list[dict[str, Any]]:
        """Get all SDN zones."""
        try:
            return proxmox_client.get_sdn_zones()
        except Exception as e:
            logger.error("Failed to get SDN zones: %s", e)
            return []

    def get_vnets(self) -> list[dict[str, Any]]:
        """Get all SDN VNets."""
        try:
            return proxmox_client.get_sdn_vnets()
        except Exception as e:
            logger.error("Failed to get SDN VNets: %s", e)
            return []

    def get_paws_zone(self) -> dict[str, Any] | None:
        """Get the PAWS VXLAN zone, if it exists."""
        zones = self.get_zones()
        for z in zones:
            if z.get("zone") == f"{ZONE_PREFIX}zone":
                return z
        return None

    def ensure_zone(self) -> str:
        """Ensure the PAWS VXLAN zone exists. Returns zone name."""
        zone_name = f"{ZONE_PREFIX}zone"
        existing = self.get_paws_zone()
        if existing:
            logger.info("PAWS SDN zone already exists: %s", zone_name)
            return zone_name

        try:
            proxmox_client.api.cluster.sdn.zones.post(
                zone=zone_name,
                type="vxlan",
                peers="",  # auto-discover peers
            )
            self._apply_sdn()
            logger.info("Created PAWS SDN zone: %s", zone_name)
        except Exception as e:
            logger.error("Failed to create SDN zone: %s", e)
            raise RuntimeError(f"Failed to create SDN zone: {e}") from e
        return zone_name

    def create_vnet(self, vnet_name: str, vxlan_tag: int, zone: str | None = None, alias: str = "") -> str:
        """Create a VNet in the PAWS zone with a VXLAN tag."""
        zone = zone or f"{ZONE_PREFIX}zone"
        try:
            proxmox_client.create_sdn_vnet(vnet_name, zone, tag=vxlan_tag, alias=alias)
            self._apply_sdn()
            logger.info("Created VNet %s (tag=%d) in zone %s", vnet_name, vxlan_tag, zone)
            return vnet_name
        except Exception as e:
            logger.error("Failed to create VNet %s: %s", vnet_name, e)
            raise RuntimeError(f"Failed to create VNet: {e}") from e

    def delete_vnet(self, vnet_name: str) -> None:
        """Delete a VNet."""
        try:
            proxmox_client.delete_sdn_vnet(vnet_name)
            self._apply_sdn()
            logger.info("Deleted VNet %s", vnet_name)
        except Exception as e:
            logger.error("Failed to delete VNet %s: %s", vnet_name, e)
            raise RuntimeError(f"Failed to delete VNet: {e}") from e

    def allocate_vxlan_tag(self) -> int:
        """Allocate the next available VXLAN tag by checking existing VNets."""
        vnets = self.get_vnets()
        used_tags = set()
        for v in vnets:
            tag = v.get("tag")
            if tag is not None:
                used_tags.add(int(tag))

        for tag in range(VXLAN_TAG_MIN, VXLAN_TAG_MAX):
            if tag not in used_tags:
                return tag
        raise RuntimeError("No available VXLAN tags")

    def generate_vnet_name(self, vpc_id: str) -> str:
        """Generate a VNet name from a VPC ID (max 8 chars for Proxmox)."""
        short_id = vpc_id.replace("-", "")[:6]
        return f"{VNET_PREFIX}{short_id}"

    def _apply_sdn(self) -> None:
        """Apply pending SDN changes on the cluster."""
        try:
            proxmox_client.api.cluster.sdn.put()
        except Exception as e:
            logger.warning("Failed to apply SDN config (may need manual apply): %s", e)


sdn_service = SDNService()

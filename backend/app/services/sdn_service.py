"""SDN (Software-Defined Networking) service for Proxmox VPC networking.

Manages EVPN zones, VNets, and subnet configurations to provide
per-user/per-VPC isolated networking via Proxmox SDN.
"""

import logging
from typing import Any

from app.services.proxmox_client import proxmox_client

logger = logging.getLogger(__name__)

# VXLAN tag range for tenant isolation
VXLAN_TAG_MIN = 10001
VXLAN_TAG_MAX = 99999

# Naming conventions
EVPN_ZONE = "paws"
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
        """Get the PAWS EVPN zone, if it exists."""
        zones = self.get_zones()
        for z in zones:
            if z.get("zone") == EVPN_ZONE:
                return z
        return None

    def get_vnet_status(self, vnet_name: str) -> dict[str, Any] | None:
        """Get a specific VNet's details from Proxmox."""
        try:
            return proxmox_client.get_sdn_vnet(vnet_name)
        except Exception as e:
            logger.error("Failed to get VNet %s: %s", vnet_name, e)
            return None

    def create_vnet(self, vnet_name: str, vxlan_tag: int, zone: str | None = None, alias: str = "") -> str:
        """Create a VNet in the PAWS EVPN zone with a VXLAN tag."""
        zone = zone or EVPN_ZONE
        try:
            proxmox_client.create_sdn_vnet(vnet_name, zone, tag=vxlan_tag, alias=alias)
            self._apply_sdn()
            logger.info("Created VNet %s (tag=%d) in zone %s", vnet_name, vxlan_tag, zone)
            return vnet_name
        except Exception as e:
            logger.error("Failed to create VNet %s: %s", vnet_name, e)
            raise RuntimeError(f"Failed to create VNet: {e}") from e

    def delete_vnet(self, vnet_name: str) -> None:
        """Delete a VNet and all its subnets."""
        try:
            subnets = self.get_subnets(vnet_name)
            for s in subnets:
                subnet_id = s.get("subnet") or s.get("cidr")
                if subnet_id:
                    try:
                        self.delete_subnet(vnet_name, subnet_id)
                    except Exception as sub_e:
                        logger.warning("Failed to delete subnet %s: %s", subnet_id, sub_e)
            proxmox_client.delete_sdn_vnet(vnet_name)
            self._apply_sdn()
            logger.info("Deleted VNet %s", vnet_name)
        except Exception as e:
            logger.error("Failed to delete VNet %s: %s", vnet_name, e)
            raise RuntimeError(f"Failed to delete VNet: {e}") from e

    def get_subnets(self, vnet_name: str) -> list[dict[str, Any]]:
        """List subnets on a VNet."""
        try:
            return proxmox_client.get_sdn_subnets(vnet_name)
        except Exception as e:
            logger.error("Failed to get subnets for VNet %s: %s", vnet_name, e)
            return []

    def create_subnet(
        self,
        vnet_name: str,
        cidr: str,
        gateway: str,
        snat: bool = True,
        dns_server: str | None = None,
    ) -> None:
        """Create a Proxmox SDN subnet on a VNet.

        DHCP is not supported on EVPN/VXLAN zones -- IPs are assigned
        statically via cloud-init (VMs) or LXC net config.

        Args:
            vnet_name: The VNet to create the subnet on
            cidr: Subnet CIDR (e.g. "10.100.1.0/24")
            gateway: Gateway IP (e.g. "10.100.1.1")
            snat: Enable SNAT for internet access
            dns_server: DNS server IP for static config
        """
        try:
            proxmox_client.create_sdn_subnet(
                vnet_name,
                cidr,
                gateway,
                snat=snat,
            )
            self._apply_sdn()
            logger.info("Created subnet %s on VNet %s (snat=%s)", cidr, vnet_name, snat)
        except Exception as e:
            logger.error("Failed to create subnet %s on %s: %s", cidr, vnet_name, e)
            raise RuntimeError(f"Failed to create subnet: {e}") from e

    def delete_subnet(self, vnet_name: str, subnet_id: str) -> None:
        """Delete a Proxmox SDN subnet.

        Args:
            vnet_name: The VNet the subnet belongs to
            subnet_id: The subnet identifier (CIDR format, e.g. "10.100.1.0-24")
        """
        try:
            proxmox_client.delete_sdn_subnet(vnet_name, subnet_id)
            self._apply_sdn()
            logger.info("Deleted subnet %s from VNet %s", subnet_id, vnet_name)
        except Exception as e:
            logger.error("Failed to delete subnet %s from %s: %s", subnet_id, vnet_name, e)
            raise RuntimeError(f"Failed to delete subnet: {e}") from e

    def allocate_vxlan_tag(self, used_db_tags: set[int] | None = None) -> int:
        """Allocate the next available VXLAN tag.

        Checks both Proxmox VNets and optionally the DB to avoid collisions.
        """
        vnets = self.get_vnets()
        used_tags: set[int] = set()
        for v in vnets:
            tag = v.get("tag")
            if tag is not None:
                used_tags.add(int(tag))

        if used_db_tags:
            used_tags.update(used_db_tags)

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
            proxmox_client.apply_sdn()
        except Exception as e:
            logger.warning("Failed to apply SDN config (may need manual apply): %s", e)


sdn_service = SDNService()

"""Translate PAWS network modes into Proxmox firewall rules.

Each managed instance has a network_mode (published, private, isolated) that
determines which firewall rules are applied.  Rules managed by this service
carry the ``[PAWS-MODE]`` comment prefix so they can be distinguished from
user-defined security-group rules (``[PAWS-SG]``).
"""

import json
import logging
from typing import Any

from app.services.proxmox_client import get_pve

logger = logging.getLogger(__name__)

COMMENT_PREFIX = "[PAWS-MODE]"
DEFAULT_LAN_RANGES = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
VALID_MODES = ("published", "private", "isolated")


class FirewallProfileService:
    """Translates PAWS network modes into Proxmox firewall rules."""

    # ------------------------------------------------------------------
    # LAN range helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_lan_ranges(db_session=None) -> list[str]:
        """Get LAN CIDR ranges from system settings, or use defaults."""
        if db_session is not None:
            try:
                from sqlalchemy import select

                from app.models.models import SystemSetting

                row = db_session.execute(
                    select(SystemSetting.value).where(SystemSetting.key == "sdn.lan_ranges")
                ).scalar_one_or_none()
                return FirewallProfileService.get_lan_ranges_from_value(row)
            except Exception:
                logger.debug("Could not load sdn.lan_ranges from DB, using defaults")
        return list(DEFAULT_LAN_RANGES)

    @staticmethod
    async def get_upstream_ips_async(db_session) -> list[str]:
        """Get upstream proxy IPs from system settings (async)."""
        try:
            from sqlalchemy import select

            from app.models.models import SystemSetting

            result = await db_session.execute(
                select(SystemSetting.value).where(SystemSetting.key == "sdn.upstream_ips")
            )
            val = result.scalar_one_or_none()
            if val:
                ips = json.loads(val)
                if isinstance(ips, list) and all(isinstance(ip, str) for ip in ips):
                    return ips
        except Exception:
            logger.debug("Could not load sdn.upstream_ips from DB")
        return []

    @staticmethod
    async def get_lan_ranges_async(db_session) -> list[str]:
        """Get LAN ranges from system settings (async)."""
        try:
            from sqlalchemy import select

            from app.models.models import SystemSetting

            result = await db_session.execute(select(SystemSetting.value).where(SystemSetting.key == "sdn.lan_ranges"))
            val = result.scalar_one_or_none()
            return FirewallProfileService.get_lan_ranges_from_value(val)
        except Exception:
            logger.debug("Could not load sdn.lan_ranges from DB, using defaults")
        return list(DEFAULT_LAN_RANGES)

    @staticmethod
    def get_lan_ranges_from_value(setting_value: str | None) -> list[str]:
        """Parse LAN ranges from a SystemSetting value string."""
        if setting_value:
            try:
                ranges = json.loads(setting_value)
                if isinstance(ranges, list) and all(isinstance(r, str) for r in ranges):
                    return ranges
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Invalid sdn.lan_ranges value: %s, using defaults",
                    setting_value,
                )
        return list(DEFAULT_LAN_RANGES)

    # ------------------------------------------------------------------
    # Rule generation
    # ------------------------------------------------------------------

    @staticmethod
    def get_rules_for_mode(
        mode: str,
        own_subnet_cidr: str,
        lan_ranges: list[str] | None = None,
        upstream_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate firewall rule kwargs for a network mode.

        Returns a list of dicts suitable for
        ``proxmox_client.create_firewall_rule(**rule)``.
        """
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid network mode '{mode}'. Must be one of {VALID_MODES}")

        if lan_ranges is None:
            lan_ranges = list(DEFAULT_LAN_RANGES)

        rules: list[dict[str, Any]] = []

        if mode == "published":
            # Allow traffic within own subnet
            rules.append(
                {
                    "type": "out",
                    "action": "ACCEPT",
                    "dest": own_subnet_cidr,
                    "comment": f"{COMMENT_PREFIX} allow own subnet",
                    "enable": 1,
                }
            )
            rules.append(
                {
                    "type": "in",
                    "action": "ACCEPT",
                    "source": own_subnet_cidr,
                    "comment": f"{COMMENT_PREFIX} allow own subnet",
                    "enable": 1,
                }
            )
            # Whitelist admin-configured upstream IPs (nginx/Cloudflare proxies)
            for up_ip in upstream_ips or []:
                rules.append(
                    {
                        "type": "in",
                        "action": "ACCEPT",
                        "source": up_ip,
                        "comment": f"{COMMENT_PREFIX} allow upstream",
                        "enable": 1,
                    }
                )
                rules.append(
                    {
                        "type": "out",
                        "action": "ACCEPT",
                        "dest": up_ip,
                        "comment": f"{COMMENT_PREFIX} allow upstream",
                        "enable": 1,
                    }
                )
            # Block each LAN range (RFC1918 etc.)
            for cidr in lan_ranges:
                rules.append(
                    {
                        "type": "out",
                        "action": "DROP",
                        "dest": cidr,
                        "comment": f"{COMMENT_PREFIX} block LAN",
                        "enable": 1,
                    }
                )
                rules.append(
                    {
                        "type": "in",
                        "action": "DROP",
                        "source": cidr,
                        "comment": f"{COMMENT_PREFIX} block LAN",
                        "enable": 1,
                    }
                )
            # Allow remaining (internet) traffic
            rules.append(
                {
                    "type": "out",
                    "action": "ACCEPT",
                    "comment": f"{COMMENT_PREFIX} allow internet",
                    "enable": 1,
                }
            )
            rules.append(
                {
                    "type": "in",
                    "action": "ACCEPT",
                    "comment": f"{COMMENT_PREFIX} allow internet",
                    "enable": 1,
                }
            )

        elif mode == "private":
            rules.append(
                {
                    "type": "out",
                    "action": "ACCEPT",
                    "comment": f"{COMMENT_PREFIX} allow all",
                    "enable": 1,
                }
            )
            rules.append(
                {
                    "type": "in",
                    "action": "ACCEPT",
                    "comment": f"{COMMENT_PREFIX} allow all",
                    "enable": 1,
                }
            )

        elif mode == "isolated":
            # Allow own subnet only, then drop everything else
            rules.append(
                {
                    "type": "out",
                    "action": "ACCEPT",
                    "dest": own_subnet_cidr,
                    "comment": f"{COMMENT_PREFIX} allow own subnet",
                    "enable": 1,
                }
            )
            rules.append(
                {
                    "type": "in",
                    "action": "ACCEPT",
                    "source": own_subnet_cidr,
                    "comment": f"{COMMENT_PREFIX} allow own subnet",
                    "enable": 1,
                }
            )
            rules.append(
                {
                    "type": "out",
                    "action": "DROP",
                    "comment": f"{COMMENT_PREFIX} block all",
                    "enable": 1,
                }
            )
            rules.append(
                {
                    "type": "in",
                    "action": "DROP",
                    "comment": f"{COMMENT_PREFIX} block all",
                    "enable": 1,
                }
            )

        return rules

    # ------------------------------------------------------------------
    # Rule application
    # ------------------------------------------------------------------

    @staticmethod
    def apply_network_mode(
        node: str,
        vmid: int,
        vmtype: str,
        mode: str,
        own_subnet_cidr: str,
        lan_ranges: list[str] | None = None,
        upstream_ips: list[str] | None = None,
        cluster_id: str | None = None,
    ) -> int:
        """Clear existing PAWS-MODE rules and apply new mode rules.

        Returns the number of rules applied.
        """
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid network mode '{mode}'. Must be one of {VALID_MODES}")

        pve = get_pve(cluster_id)
        deleted = pve.clear_firewall_rules_by_comment(node, vmid, vmtype, COMMENT_PREFIX)
        if deleted:
            logger.info("Cleared %d existing PAWS-MODE rules on %s/%s", deleted, node, vmid)

        rules = FirewallProfileService.get_rules_for_mode(mode, own_subnet_cidr, lan_ranges, upstream_ips=upstream_ips)

        for rule in rules:
            pve.create_firewall_rule(node, vmid, vmtype, **rule)

        logger.info(
            "Applied %d firewall rules for mode '%s' on %s/%s",
            len(rules),
            mode,
            node,
            vmid,
        )
        return len(rules)

    # ------------------------------------------------------------------
    # Firewall enable / sync
    # ------------------------------------------------------------------

    @staticmethod
    def enable_firewall(node: str, vmid: int, vmtype: str, cluster_id: str | None = None) -> None:
        """Enable the Proxmox firewall on a VM or container."""
        get_pve(cluster_id).set_firewall_options(node, vmid, vmtype, enable=1)
        logger.info("Enabled firewall on %s/%s (type=%s)", node, vmid, vmtype)

    @staticmethod
    def sync_firewall(
        node: str,
        vmid: int,
        vmtype: str,
        mode: str,
        own_subnet_cidr: str,
        lan_ranges: list[str] | None = None,
        upstream_ips: list[str] | None = None,
        cluster_id: str | None = None,
    ) -> int:
        """Re-apply current mode rules (e.g. after migration).

        Equivalent to :meth:`apply_network_mode`.
        """
        return FirewallProfileService.apply_network_mode(
            node,
            vmid,
            vmtype,
            mode,
            own_subnet_cidr,
            lan_ranges,
            upstream_ips=upstream_ips,
            cluster_id=cluster_id,
        )

    # ------------------------------------------------------------------
    # Bandwidth limiting
    # ------------------------------------------------------------------

    @staticmethod
    def apply_bandwidth_limit(node: str, vmid: int, vmtype: str, rate_mbps: int, cluster_id: str | None = None) -> None:
        """Set NIC rate limit via Proxmox config (net0 rate parameter).

        The Proxmox ``rate`` parameter is in MB/s.
        A *rate_mbps* of ``0`` means unlimited (the parameter is removed).
        """
        if rate_mbps < 0:
            raise ValueError("rate_mbps must be >= 0")

        pve = get_pve(cluster_id)
        if vmtype == "lxc":
            current = pve.get_container_config(node, vmid)
            net0_value = current.get("net0", "")
            net0_updated = _update_net0_rate(net0_value, rate_mbps)
            pve.set_container_config(node, vmid, net0=net0_updated)
        else:
            current = pve.get_vm_config(node, vmid)
            net0_value = current.get("net0", "")
            net0_updated = _update_net0_rate(net0_value, rate_mbps)
            pve.update_vm_config(node, vmid, net0=net0_updated)

        if rate_mbps:
            logger.info("Set bandwidth limit to %d MB/s on %s/%s", rate_mbps, node, vmid)
        else:
            logger.info("Removed bandwidth limit on %s/%s", node, vmid)

    @staticmethod
    def get_effective_bandwidth(tier_bandwidth: int | None, resource_bandwidth: int | None) -> int:
        """Return the effective bandwidth limit in MB/s.

        Priority: resource override > tier default > system default (100).
        """
        if resource_bandwidth is not None:
            return resource_bandwidth
        if tier_bandwidth is not None:
            return tier_bandwidth
        return 100


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _update_net0_rate(net0_str: str, rate_mbps: int) -> str:
    """Insert or update the ``rate=<N>`` parameter in a net0 config string.

    If *rate_mbps* is ``0`` the rate key is removed (unlimited).
    """
    parts = [p for p in net0_str.split(",") if p]
    filtered = [p for p in parts if not p.strip().startswith("rate=")]

    if rate_mbps > 0:
        filtered.append(f"rate={rate_mbps}")

    return ",".join(filtered)

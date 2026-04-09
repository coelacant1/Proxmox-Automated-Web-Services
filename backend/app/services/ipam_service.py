"""CIDR pool allocator and IP address management (IPAM) service.

Allocates non-overlapping VPC CIDRs from a configurable supernet.
Each VPC gets a single /24 subnet. Tracks IP assignments for instances.
"""

import ipaddress
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import VPC, Subnet

logger = logging.getLogger(__name__)

# Default supernet for VPC allocation
DEFAULT_SUPERNET = "10.0.0.0/8"
DEFAULT_VPC_PREFIX = 24  # /24 per VPC = one subnet per network


class CIDRPool:
    """Allocates non-overlapping CIDR blocks from a supernet."""

    def __init__(self, supernet: str = DEFAULT_SUPERNET, vpc_prefix: int = DEFAULT_VPC_PREFIX):
        self.supernet = ipaddress.ip_network(supernet, strict=False)
        self.vpc_prefix = vpc_prefix

    def get_available_vpc_cidr(self, used_cidrs: list[str]) -> str:
        """Find the next available VPC CIDR block (globally unique)."""
        used_networks = [ipaddress.ip_network(c, strict=False) for c in used_cidrs]

        for candidate in self.supernet.subnets(new_prefix=self.vpc_prefix):
            if not any(candidate.overlaps(used) for used in used_networks):
                return str(candidate)

        raise RuntimeError("No available VPC CIDR blocks in the pool")

    @staticmethod
    def validate_cidr(cidr: str) -> bool:
        """Validate a CIDR string."""
        try:
            ipaddress.ip_network(cidr, strict=False)
            return True
        except ValueError:
            return False

    @staticmethod
    def is_subnet_of(child: str, parent: str) -> bool:
        """Check if child CIDR is a subnet of parent CIDR."""
        child_net = ipaddress.ip_network(child, strict=False)
        parent_net = ipaddress.ip_network(parent, strict=False)
        return child_net.subnet_of(parent_net)

    @staticmethod
    def get_gateway(cidr: str) -> str:
        """Get the first usable IP as the gateway."""
        net = ipaddress.ip_network(cidr, strict=False)
        return str(list(net.hosts())[0])

    @staticmethod
    def get_host_count(cidr: str) -> int:
        """Get the number of usable hosts in a CIDR."""
        net = ipaddress.ip_network(cidr, strict=False)
        return net.num_addresses - 2  # subtract network and broadcast


class IPAMService:
    """IP Address Management - allocates and tracks IPs within subnets."""

    def __init__(self):
        self.cidr_pool = CIDRPool()

    async def allocate_vpc_cidr(self, db: AsyncSession) -> str:
        """Allocate the next available VPC CIDR."""
        result = await db.execute(select(VPC.cidr))
        used = [row[0] for row in result.all() if row[0]]
        return self.cidr_pool.get_available_vpc_cidr(used)

    async def check_cidr_globally_unique(self, db: AsyncSession, cidr: str) -> bool:
        """Check that a CIDR does not overlap with any existing VPC."""
        candidate = ipaddress.ip_network(cidr, strict=False)
        result = await db.execute(select(VPC.cidr))
        for row in result.all():
            if row[0] and ipaddress.ip_network(row[0], strict=False).overlaps(candidate):
                return False
        return True

    def get_next_ip(self, cidr: str, used_ips: list[str]) -> str:
        """Get the next available IP in a subnet (skip gateway)."""
        net = ipaddress.ip_network(cidr, strict=False)
        used_set = set(used_ips)
        hosts = list(net.hosts())

        # Skip first IP (gateway)
        for host in hosts[1:]:
            if str(host) not in used_set:
                return str(host)

        raise RuntimeError(f"No available IPs in {cidr}")

    def get_subnet_info(self, cidr: str) -> dict[str, Any]:
        """Get subnet metadata."""
        net = ipaddress.ip_network(cidr, strict=False)
        hosts = list(net.hosts())
        return {
            "network": str(net.network_address),
            "broadcast": str(net.broadcast_address),
            "netmask": str(net.netmask),
            "gateway": str(hosts[0]) if hosts else None,
            "first_usable": str(hosts[1]) if len(hosts) > 1 else None,
            "last_usable": str(hosts[-1]) if hosts else None,
            "total_hosts": len(hosts) - 1,  # minus gateway
            "prefix_length": net.prefixlen,
        }


cidr_pool = CIDRPool()
ipam_service = IPAMService()

"""IPAM and CIDR pool allocator tests."""

import pytest

from app.services.ipam_service import CIDRPool, IPAMService


class TestCIDRPool:
    def test_get_available_vpc_cidr_first(self):
        pool = CIDRPool("10.0.0.0/8", vpc_prefix=24)
        cidr = pool.get_available_vpc_cidr([])
        assert cidr == "10.0.0.0/24"

    def test_get_available_vpc_cidr_skips_used(self):
        pool = CIDRPool("10.0.0.0/8", vpc_prefix=24)
        cidr = pool.get_available_vpc_cidr(["10.0.0.0/24", "10.0.1.0/24"])
        assert cidr == "10.0.2.0/24"

    def test_validate_cidr_valid(self):
        assert CIDRPool.validate_cidr("10.0.0.0/16")
        assert CIDRPool.validate_cidr("192.168.1.0/24")

    def test_validate_cidr_invalid(self):
        assert not CIDRPool.validate_cidr("not-a-cidr")
        assert not CIDRPool.validate_cidr("10.0.0.0/33")

    def test_is_subnet_of(self):
        assert CIDRPool.is_subnet_of("10.0.1.0/24", "10.0.0.0/16")
        assert not CIDRPool.is_subnet_of("192.168.0.0/24", "10.0.0.0/16")

    def test_get_gateway(self):
        gw = CIDRPool.get_gateway("10.0.1.0/24")
        assert gw == "10.0.1.1"

    def test_get_host_count(self):
        count = CIDRPool.get_host_count("10.0.0.0/24")
        assert count == 254


class TestIPAMService:
    def test_get_next_ip(self):
        ipam = IPAMService()
        ip = ipam.get_next_ip("10.0.0.0/24", [])
        assert ip == "10.0.0.2"  # skip .1 (gateway)

    def test_get_next_ip_skips_used(self):
        ipam = IPAMService()
        ip = ipam.get_next_ip("10.0.0.0/24", ["10.0.0.2", "10.0.0.3"])
        assert ip == "10.0.0.4"

    def test_get_next_ip_exhausted(self):
        ipam = IPAMService()
        # /30 has only 2 usable hosts: .1 (gw) and .2
        with pytest.raises(RuntimeError, match="No available IPs"):
            ipam.get_next_ip("10.0.0.0/30", ["10.0.0.2"])

    def test_get_subnet_info(self):
        ipam = IPAMService()
        info = ipam.get_subnet_info("10.0.1.0/24")
        assert info["network"] == "10.0.1.0"
        assert info["broadcast"] == "10.0.1.255"
        assert info["gateway"] == "10.0.1.1"
        assert info["total_hosts"] == 253
        assert info["prefix_length"] == 24

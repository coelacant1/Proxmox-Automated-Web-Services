"""SDN service tests."""

import pytest

from app.services.sdn_service import SDNService, VXLAN_TAG_MIN


def test_generate_vnet_name():
    sdn = SDNService()
    name = sdn.generate_vnet_name("abc12345-def6-7890-abcd-ef1234567890")
    assert name.startswith("pv")
    assert len(name) <= 8


def test_allocate_vxlan_tag_empty(monkeypatch):
    sdn = SDNService()
    monkeypatch.setattr(sdn, "get_vnets", lambda: [])
    tag = sdn.allocate_vxlan_tag()
    assert tag == VXLAN_TAG_MIN


def test_allocate_vxlan_tag_skips_used(monkeypatch):
    sdn = SDNService()
    monkeypatch.setattr(sdn, "get_vnets", lambda: [{"tag": VXLAN_TAG_MIN}, {"tag": VXLAN_TAG_MIN + 1}])
    tag = sdn.allocate_vxlan_tag()
    assert tag == VXLAN_TAG_MIN + 2


def test_get_paws_zone_found(monkeypatch):
    sdn = SDNService()
    monkeypatch.setattr(sdn, "get_zones", lambda: [{"zone": "paws", "type": "evpn"}])
    zone = sdn.get_paws_zone()
    assert zone is not None
    assert zone["zone"] == "paws"


def test_get_paws_zone_not_found(monkeypatch):
    sdn = SDNService()
    monkeypatch.setattr(sdn, "get_zones", lambda: [{"zone": "otherzone", "type": "simple"}])
    zone = sdn.get_paws_zone()
    assert zone is None

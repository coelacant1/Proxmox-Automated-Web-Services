"""Networking router tests."""

import pytest


@pytest.mark.anyio
async def test_list_sdn_zones(auth_client):
    resp = await auth_client.get("/api/networking/zones")
    assert resp.status_code == 200
    zones = resp.json()
    assert len(zones) >= 1
    assert zones[0]["zone"] == "vxlan1"


@pytest.mark.anyio
async def test_list_vnets(auth_client):
    resp = await auth_client.get("/api/networking/vnets")
    assert resp.status_code == 200
    vnets = resp.json()
    assert len(vnets) >= 1
    assert vnets[0]["vnet"] == "vnet1"


@pytest.mark.anyio
async def test_vm_firewall_rules(auth_client):
    resp = await auth_client.get("/api/networking/vms/pve1/100/firewall")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_networking_unauthenticated(client):
    resp = await client.get("/api/networking/zones")
    assert resp.status_code == 401

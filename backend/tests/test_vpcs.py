"""Tests for VPC management (single subnet per network)."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient


def _mock_sdn():
    """Return a patch context that mocks all SDN service calls."""
    return patch.multiple(
        "app.services.sdn_service.sdn_service",
        allocate_vxlan_tag=lambda *a, **kw: 10001,
        generate_vnet_name=lambda self_or_id, *a: "pvtest01",
        create_vnet=lambda *a, **kw: "pvtest01",
        delete_vnet=lambda *a, **kw: None,
        create_subnet=lambda *a, **kw: None,
        delete_subnet=lambda *a, **kw: None,
        get_subnets=lambda *a, **kw: [],
    )


@pytest.mark.asyncio
async def test_list_vpcs_empty(auth_client: AsyncClient):
    r = await auth_client.get("/api/vpcs/")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_and_list_vpc(auth_client: AsyncClient):
    with _mock_sdn():
        r = await auth_client.post("/api/vpcs/", json={"name": "my-vpc", "cidr": "10.0.0.0/24"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "my-vpc"
    assert data["cidr"] == "10.0.0.0/24"
    assert data["status"] == "active"
    # Single subnet auto-created with same CIDR as the network
    assert len(data["subnets"]) == 1
    assert data["subnets"][0]["cidr"] == "10.0.0.0/24"

    vpcs = await auth_client.get("/api/vpcs/")
    assert len(vpcs.json()) == 1


@pytest.mark.asyncio
async def test_get_vpc(auth_client: AsyncClient):
    with _mock_sdn():
        create = await auth_client.post("/api/vpcs/", json={"name": "get-vpc"})
    vpc_id = create.json()["id"]
    r = await auth_client.get(f"/api/vpcs/{vpc_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "get-vpc"
    assert len(r.json()["subnets"]) == 1


@pytest.mark.asyncio
async def test_delete_vpc(auth_client: AsyncClient):
    with _mock_sdn():
        create = await auth_client.post("/api/vpcs/", json={"name": "del-vpc"})
    vpc_id = create.json()["id"]
    with _mock_sdn():
        r = await auth_client.delete(f"/api/vpcs/{vpc_id}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_cannot_delete_default_vpc(auth_client: AsyncClient, db_session):
    from app.models.models import VPC
    from tests.conftest import TEST_USER_ID

    vpc = VPC(owner_id=TEST_USER_ID, name="default-vpc", cidr="10.0.0.0/24", is_default=True)
    db_session.add(vpc)
    await db_session.commit()
    await db_session.refresh(vpc)

    with _mock_sdn():
        r = await auth_client.delete(f"/api/vpcs/{vpc.id}")
    assert r.status_code == 400
    assert "Cannot delete default" in r.json()["detail"]


@pytest.mark.asyncio
async def test_duplicate_vpc_name(auth_client: AsyncClient):
    with _mock_sdn():
        await auth_client.post("/api/vpcs/", json={"name": "dup-vpc"})
        r = await auth_client.post("/api/vpcs/", json={"name": "dup-vpc"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_cidr_uniqueness(auth_client: AsyncClient):
    """Two networks cannot have overlapping CIDRs."""
    with _mock_sdn():
        r1 = await auth_client.post("/api/vpcs/", json={"name": "net-a", "cidr": "10.50.0.0/24"})
        assert r1.status_code == 201
        r2 = await auth_client.post("/api/vpcs/", json={"name": "net-b", "cidr": "10.50.0.0/24"})
        assert r2.status_code == 409
        assert "overlap" in r2.json()["detail"].lower() or "unique" in r2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_default_security_group_on_register(client: AsyncClient):
    """Registration should auto-create a default security group."""
    r = await client.post(
        "/api/auth/register",
        json={
            "email": "sgtest@test.com",
            "username": "sguser",
            "password": "StrongP@ss1!",
            "full_name": "SG Test User",
        },
    )
    assert r.status_code == 201

    login = await client.post(
        "/api/auth/login",
        json={
            "username": "sguser",
            "password": "StrongP@ss1!",
        },
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sgs = await client.get("/api/security-groups/", headers=headers)
    assert sgs.status_code == 200
    sg_list = sgs.json()
    assert len(sg_list) == 1
    assert sg_list[0]["name"] == "default"
    assert len(sg_list[0]["rules"]) == 4  # 2 egress + SSH + ICMP

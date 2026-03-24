"""Tests for instance type management."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_instance_types_empty(auth_client: AsyncClient):
    r = await auth_client.get("/api/instance-types/")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_instance_type_admin(admin_client: AsyncClient):
    r = await admin_client.post(
        "/api/instance-types/",
        json={
            "name": "paws.test",
            "vcpus": 2,
            "ram_mib": 2048,
            "disk_gib": 40,
            "category": "general",
            "description": "Test instance type",
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "paws.test"
    assert data["vcpus"] == 2
    assert data["ram_mib"] == 2048
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_instance_type_non_admin_forbidden(auth_client: AsyncClient):
    r = await auth_client.post(
        "/api/instance-types/",
        json={
            "name": "paws.forbidden",
            "vcpus": 1,
            "ram_mib": 512,
            "disk_gib": 10,
            "category": "general",
        },
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_duplicate_name_rejected(admin_client: AsyncClient):
    await admin_client.post(
        "/api/instance-types/",
        json={
            "name": "paws.dup",
            "vcpus": 1,
            "ram_mib": 512,
            "disk_gib": 10,
            "category": "general",
        },
    )
    r = await admin_client.post(
        "/api/instance-types/",
        json={
            "name": "paws.dup",
            "vcpus": 2,
            "ram_mib": 1024,
            "disk_gib": 20,
            "category": "general",
        },
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_update_instance_type(admin_client: AsyncClient):
    create = await admin_client.post(
        "/api/instance-types/",
        json={
            "name": "paws.update",
            "vcpus": 1,
            "ram_mib": 512,
            "disk_gib": 10,
            "category": "general",
        },
    )
    it_id = create.json()["id"]

    r = await admin_client.patch(f"/api/instance-types/{it_id}", json={"vcpus": 4, "description": "Updated"})
    assert r.status_code == 200
    assert r.json()["vcpus"] == 4
    assert r.json()["description"] == "Updated"


@pytest.mark.asyncio
async def test_delete_instance_type(admin_client: AsyncClient):
    create = await admin_client.post(
        "/api/instance-types/",
        json={
            "name": "paws.delete",
            "vcpus": 1,
            "ram_mib": 512,
            "disk_gib": 10,
            "category": "general",
        },
    )
    it_id = create.json()["id"]

    r = await admin_client.delete(f"/api/instance-types/{it_id}")
    assert r.status_code == 204

    # Verify it's gone
    r = await admin_client.get("/api/instance-types/")
    names = [t["name"] for t in r.json()]
    assert "paws.delete" not in names


@pytest.mark.asyncio
async def test_filter_by_category(admin_client: AsyncClient):
    await admin_client.post(
        "/api/instance-types/",
        json={
            "name": "paws.gen.1",
            "vcpus": 1,
            "ram_mib": 512,
            "disk_gib": 10,
            "category": "general",
        },
    )
    await admin_client.post(
        "/api/instance-types/",
        json={
            "name": "paws.comp.1",
            "vcpus": 4,
            "ram_mib": 2048,
            "disk_gib": 20,
            "category": "compute",
        },
    )

    r = await admin_client.get("/api/instance-types/?category=compute")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["name"] == "paws.comp.1"

"""Tests for SSH keys, security groups, and volumes APIs."""

import pytest
from httpx import AsyncClient


# --- SSH Keys ------------------------------------------------------------


TEST_SSH_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl test@paws"


@pytest.mark.asyncio
async def test_list_ssh_keys_empty(auth_client: AsyncClient):
    r = await auth_client.get("/api/ssh-keys/")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_and_list_ssh_key(auth_client: AsyncClient):
    r = await auth_client.post("/api/ssh-keys/", json={"name": "my-key", "public_key": TEST_SSH_KEY})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "my-key"
    assert data["fingerprint"]
    assert ":" in data["fingerprint"]

    keys = await auth_client.get("/api/ssh-keys/")
    assert len(keys.json()) == 1


@pytest.mark.asyncio
async def test_create_ssh_key_invalid_format(auth_client: AsyncClient):
    r = await auth_client.post("/api/ssh-keys/", json={"name": "bad", "public_key": "not-a-key"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_ssh_key_duplicate_name(auth_client: AsyncClient):
    await auth_client.post("/api/ssh-keys/", json={"name": "dup", "public_key": TEST_SSH_KEY})
    r = await auth_client.post("/api/ssh-keys/", json={"name": "dup", "public_key": TEST_SSH_KEY})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_delete_ssh_key(auth_client: AsyncClient):
    create = await auth_client.post("/api/ssh-keys/", json={"name": "del-key", "public_key": TEST_SSH_KEY})
    key_id = create.json()["id"]
    r = await auth_client.delete(f"/api/ssh-keys/{key_id}")
    assert r.status_code == 204


# --- Security Groups ----------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_list_security_group(auth_client: AsyncClient):
    r = await auth_client.post("/api/security-groups/", json={"name": "web-sg", "description": "Web traffic"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "web-sg"
    assert data["rules"] == []

    sgs = await auth_client.get("/api/security-groups/")
    assert len(sgs.json()) == 1


@pytest.mark.asyncio
async def test_add_rule_to_security_group(auth_client: AsyncClient):
    sg = await auth_client.post("/api/security-groups/", json={"name": "rule-test"})
    sg_id = sg.json()["id"]

    r = await auth_client.post(f"/api/security-groups/{sg_id}/rules", json={
        "direction": "ingress",
        "protocol": "tcp",
        "port_from": 80,
        "port_to": 80,
        "cidr": "0.0.0.0/0",
        "description": "HTTP",
    })
    assert r.status_code == 201
    assert r.json()["port_from"] == 80

    # Fetch SG and verify rule
    sg_data = await auth_client.get(f"/api/security-groups/{sg_id}")
    assert len(sg_data.json()["rules"]) == 1


@pytest.mark.asyncio
async def test_delete_rule_from_security_group(auth_client: AsyncClient):
    sg = await auth_client.post("/api/security-groups/", json={"name": "del-rule-test"})
    sg_id = sg.json()["id"]
    rule = await auth_client.post(f"/api/security-groups/{sg_id}/rules", json={
        "direction": "egress", "protocol": "tcp", "port_from": 443, "port_to": 443,
    })
    rule_id = rule.json()["id"]

    r = await auth_client.delete(f"/api/security-groups/{sg_id}/rules/{rule_id}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_security_group(auth_client: AsyncClient):
    sg = await auth_client.post("/api/security-groups/", json={"name": "to-delete"})
    sg_id = sg.json()["id"]
    r = await auth_client.delete(f"/api/security-groups/{sg_id}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_invalid_rule_direction(auth_client: AsyncClient):
    sg = await auth_client.post("/api/security-groups/", json={"name": "bad-dir"})
    sg_id = sg.json()["id"]
    r = await auth_client.post(f"/api/security-groups/{sg_id}/rules", json={
        "direction": "invalid", "protocol": "tcp",
    })
    assert r.status_code == 422


# --- Volumes ------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_list_volume(auth_client: AsyncClient):
    r = await auth_client.post("/api/volumes/", json={"name": "data-vol", "size_gib": 50})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "data-vol"
    assert data["size_gib"] == 50
    assert data["status"] == "available"

    vols = await auth_client.get("/api/volumes/")
    assert len(vols.json()) == 1


@pytest.mark.asyncio
async def test_volume_size_validation(auth_client: AsyncClient):
    r = await auth_client.post("/api/volumes/", json={"name": "too-big", "size_gib": 99999})
    assert r.status_code == 422

    r = await auth_client.post("/api/volumes/", json={"name": "too-small", "size_gib": 0})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_volume(auth_client: AsyncClient):
    create = await auth_client.post("/api/volumes/", json={"name": "del-vol", "size_gib": 10})
    vol_id = create.json()["id"]
    r = await auth_client.delete(f"/api/volumes/{vol_id}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_get_volume(auth_client: AsyncClient):
    create = await auth_client.post("/api/volumes/", json={"name": "get-vol", "size_gib": 20})
    vol_id = create.json()["id"]
    r = await auth_client.get(f"/api/volumes/{vol_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "get-vol"


@pytest.mark.asyncio
async def test_volume_resize(auth_client: AsyncClient):
    create = await auth_client.post("/api/volumes/", json={"name": "resize-vol", "size_gib": 10})
    vol_id = create.json()["id"]

    # Grow
    r = await auth_client.post(f"/api/volumes/{vol_id}/resize", json={"size_gib": 20})
    assert r.status_code == 200

    # Verify size
    detail = await auth_client.get(f"/api/volumes/{vol_id}")
    assert detail.json()["size_gib"] == 20


@pytest.mark.asyncio
async def test_volume_resize_shrink_rejected(auth_client: AsyncClient):
    create = await auth_client.post("/api/volumes/", json={"name": "no-shrink-vol", "size_gib": 20})
    vol_id = create.json()["id"]

    r = await auth_client.post(f"/api/volumes/{vol_id}/resize", json={"size_gib": 10})
    assert r.status_code == 400
    assert "larger" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_volume_snapshot(auth_client: AsyncClient):
    create = await auth_client.post("/api/volumes/", json={"name": "snap-vol", "size_gib": 10})
    vol_id = create.json()["id"]

    r = await auth_client.post(f"/api/volumes/{vol_id}/snapshot", json={"name": "snap1"})
    assert r.status_code == 200

"""Backups router tests."""

import pytest


@pytest.mark.anyio
async def test_list_snapshots_for_vm(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "backup-vm",
            "template_vmid": 9000,
        },
    )
    vm_id = create.json()["id"]

    resp = await auth_client.get(f"/api/backups/{vm_id}/snapshots")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_create_snapshot(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "snap-target",
            "template_vmid": 9000,
        },
    )
    vm_id = create.json()["id"]

    resp = await auth_client.post(
        f"/api/backups/{vm_id}/snapshots",
        json={
            "name": "before-upgrade",
            "description": "Snapshot before OS upgrade",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "creating"


@pytest.mark.anyio
async def test_rollback_snapshot(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "rollback-vm",
            "template_vmid": 9000,
        },
    )
    vm_id = create.json()["id"]

    resp = await auth_client.post(f"/api/backups/{vm_id}/snapshots/rollback", json={"name": "snap1"})
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_delete_snapshot(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "del-snap-vm",
            "template_vmid": 9000,
        },
    )
    vm_id = create.json()["id"]

    resp = await auth_client.delete(f"/api/backups/{vm_id}/snapshots/old-snap")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_snapshot_for_nonexistent_resource(auth_client):
    import uuid

    fake_id = str(uuid.uuid4())
    resp = await auth_client.get(f"/api/backups/{fake_id}/snapshots")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_snapshots_unauthenticated(client):
    import uuid

    resp = await client.get(f"/api/backups/{uuid.uuid4()}/snapshots")
    assert resp.status_code == 401

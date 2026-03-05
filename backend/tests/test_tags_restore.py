"""Tests for tags, restore APIs, and volume operations."""

import json
import uuid

import pytest

from app.models.models import Backup, Resource
from tests.conftest import TEST_USER_ID


async def _make_resource(db_session, name="tag-vm", status="running"):
    r = Resource(
        id=uuid.uuid4(),
        owner_id=TEST_USER_ID,
        resource_type="vm",
        display_name=name,
        status=status,
        specs=json.dumps({"cpu": 2, "ram_mb": 2048, "disk_gb": 20}),
        proxmox_vmid=700 + hash(name) % 200,
        proxmox_node="node1",
    )
    db_session.add(r)
    await db_session.commit()
    return str(r.id)


# --- Tags CRUD ------------------------------------------------------------


@pytest.mark.anyio
async def test_create_and_list_tags(auth_client, db_session):
    vm_id = await _make_resource(db_session, "tag-vm-1")
    r = await auth_client.post("/api/tags/", json={"resource_id": vm_id, "key": "env", "value": "dev"})
    assert r.status_code == 201
    assert r.json()["key"] == "env"

    r2 = await auth_client.get(f"/api/tags/resource/{vm_id}")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


@pytest.mark.anyio
async def test_batch_set_tags(auth_client, db_session):
    vm_id = await _make_resource(db_session, "tag-batch")
    r = await auth_client.put(
        "/api/tags/batch",
        json={"resource_id": vm_id, "tags": {"project": "web", "tier": "frontend"}},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2

    r2 = await auth_client.get(f"/api/tags/resource/{vm_id}")
    assert len(r2.json()) == 2


@pytest.mark.anyio
async def test_delete_tag(auth_client, db_session):
    vm_id = await _make_resource(db_session, "tag-del")
    r = await auth_client.post("/api/tags/", json={"resource_id": vm_id, "key": "temp"})
    tag_id = r.json()["id"]

    r2 = await auth_client.delete(f"/api/tags/{tag_id}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "deleted"


@pytest.mark.anyio
async def test_duplicate_tag_key(auth_client, db_session):
    vm_id = await _make_resource(db_session, "tag-dup")
    await auth_client.post("/api/tags/", json={"resource_id": vm_id, "key": "unique"})
    r = await auth_client.post("/api/tags/", json={"resource_id": vm_id, "key": "unique"})
    assert r.status_code == 409


@pytest.mark.anyio
async def test_clear_all_tags(auth_client, db_session):
    vm_id = await _make_resource(db_session, "tag-clear")
    await auth_client.put(
        "/api/tags/batch",
        json={"resource_id": vm_id, "tags": {"a": "1", "b": "2", "c": "3"}},
    )
    r = await auth_client.delete(f"/api/tags/resource/{vm_id}")
    assert r.status_code == 200

    r2 = await auth_client.get(f"/api/tags/resource/{vm_id}")
    assert len(r2.json()) == 0


# --- Restore APIs ---------------------------------------------------------


@pytest.mark.anyio
async def test_restore_inplace(auth_client, db_session):
    vm_id = await _make_resource(db_session, "restore-vm")
    backup = Backup(
        id=uuid.uuid4(),
        resource_id=uuid.UUID(vm_id),
        owner_id=TEST_USER_ID,
        backup_type="snapshot",
        status="completed",
    )
    db_session.add(backup)
    await db_session.commit()

    r = await auth_client.post(f"/api/backups/{backup.id}/restore-inplace")
    assert r.status_code == 200
    assert r.json()["status"] == "restoring"


@pytest.mark.anyio
async def test_restore_to_new(auth_client, db_session):
    vm_id = await _make_resource(db_session, "restore-new-src")
    backup = Backup(
        id=uuid.uuid4(),
        resource_id=uuid.UUID(vm_id),
        owner_id=TEST_USER_ID,
        backup_type="snapshot",
        status="completed",
    )
    db_session.add(backup)
    await db_session.commit()

    r = await auth_client.post(
        f"/api/backups/{backup.id}/restore-new",
        json={"name": "restored-vm"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "restoring"
    assert "new_resource_id" in r.json()


@pytest.mark.anyio
async def test_restore_incomplete_backup(auth_client, db_session):
    vm_id = await _make_resource(db_session, "restore-pending")
    backup = Backup(
        id=uuid.uuid4(),
        resource_id=uuid.UUID(vm_id),
        owner_id=TEST_USER_ID,
        backup_type="snapshot",
        status="running",
    )
    db_session.add(backup)
    await db_session.commit()

    r = await auth_client.post(f"/api/backups/{backup.id}/restore-inplace")
    assert r.status_code == 400


@pytest.mark.anyio
async def test_list_restore_jobs(auth_client):
    r = await auth_client.get("/api/backups/restore-jobs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# --- Volume Operations ----------------------------------------------------


@pytest.mark.anyio
async def test_volume_resize(auth_client):
    cr = await auth_client.post("/api/volumes/", json={"name": "resize-vol", "size_gib": 10})
    vol_id = cr.json()["id"]

    r = await auth_client.post(f"/api/volumes/{vol_id}/resize", json={"size_gib": 20})
    assert r.status_code == 200
    assert "20" in r.json()["message"]


@pytest.mark.anyio
async def test_volume_resize_must_grow(auth_client):
    cr = await auth_client.post("/api/volumes/", json={"name": "shrink-vol", "size_gib": 50})
    vol_id = cr.json()["id"]

    r = await auth_client.post(f"/api/volumes/{vol_id}/resize", json={"size_gib": 30})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_volume_snapshot(auth_client):
    cr = await auth_client.post("/api/volumes/", json={"name": "snap-vol", "size_gib": 5})
    vol_id = cr.json()["id"]

    r = await auth_client.post(f"/api/volumes/{vol_id}/snapshot", json={"name": "snap1"})
    assert r.status_code == 200
    assert "snap1" in r.json()["message"]

"""Tests for lifecycle policies, events, suspend/resume, and object copy/move."""

import json
import uuid

import pytest

from app.models.models import Event, Resource
from tests.conftest import TEST_USER_ID


async def _make_resource(db_session, name="lc-vm", status="running"):
    r = Resource(
        id=uuid.uuid4(),
        owner_id=TEST_USER_ID,
        resource_type="vm",
        display_name=name,
        status=status,
        specs=json.dumps({"cpu": 2, "ram_mb": 2048, "disk_gb": 20}),
        proxmox_vmid=400 + hash(name) % 500,
        proxmox_node="node1",
    )
    db_session.add(r)
    await db_session.commit()
    return str(r.id)


# --- Lifecycle Policies --------------------------------------------------


@pytest.mark.anyio
async def test_create_lifecycle_policy(auth_client, db_session):
    vm_id = await _make_resource(db_session, "lp-vm")
    r = await auth_client.post(
        "/api/lifecycle/policies",
        json={
            "resource_id": vm_id,
            "policy_type": "auto_stop",
            "action": "stop",
            "cron_expression": "0 22 * * *",
        },
    )
    assert r.status_code == 201
    assert r.json()["policy_type"] == "auto_stop"
    assert r.json()["action"] == "stop"


@pytest.mark.anyio
async def test_list_lifecycle_policies(auth_client, db_session):
    vm_id = await _make_resource(db_session, "lp-list")
    await auth_client.post(
        "/api/lifecycle/policies",
        json={"resource_id": vm_id, "policy_type": "ttl", "action": "terminate"},
    )
    r = await auth_client.get("/api/lifecycle/policies")
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.anyio
async def test_update_lifecycle_policy(auth_client, db_session):
    vm_id = await _make_resource(db_session, "lp-upd")
    cr = await auth_client.post(
        "/api/lifecycle/policies",
        json={"resource_id": vm_id, "policy_type": "schedule", "action": "start"},
    )
    policy_id = cr.json()["id"]
    r = await auth_client.patch(
        f"/api/lifecycle/policies/{policy_id}",
        json={"is_active": False},
    )
    assert r.status_code == 200


@pytest.mark.anyio
async def test_delete_lifecycle_policy(auth_client, db_session):
    vm_id = await _make_resource(db_session, "lp-del")
    cr = await auth_client.post(
        "/api/lifecycle/policies",
        json={"resource_id": vm_id, "policy_type": "auto_start", "action": "start"},
    )
    policy_id = cr.json()["id"]
    r = await auth_client.delete(f"/api/lifecycle/policies/{policy_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"


@pytest.mark.anyio
async def test_lifecycle_policy_invalid_type(auth_client, db_session):
    vm_id = await _make_resource(db_session, "lp-bad")
    r = await auth_client.post(
        "/api/lifecycle/policies",
        json={"resource_id": vm_id, "policy_type": "invalid", "action": "stop"},
    )
    assert r.status_code == 422


# --- Events --------------------------------------------------------------


@pytest.mark.anyio
async def test_list_events_empty(auth_client):
    r = await auth_client.get("/api/events/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.anyio
async def test_list_events_with_data(auth_client, db_session):
    event = Event(
        event_type="instance_start",
        source="compute",
        user_id=TEST_USER_ID,
        severity="info",
        message="VM started",
    )
    db_session.add(event)
    await db_session.commit()

    r = await auth_client.get("/api/events/")
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.anyio
async def test_list_events_filter_source(auth_client, db_session):
    event = Event(
        event_type="backup_complete",
        source="backup",
        user_id=TEST_USER_ID,
        severity="info",
        message="Backup done",
    )
    db_session.add(event)
    await db_session.commit()

    r = await auth_client.get("/api/events/?source=backup")
    assert r.status_code == 200
    for e in r.json():
        assert e["source"] == "backup"


@pytest.mark.anyio
async def test_get_event(auth_client, db_session):
    event = Event(
        event_type="test_event",
        source="system",
        user_id=TEST_USER_ID,
        severity="warning",
        message="Test warning",
    )
    db_session.add(event)
    await db_session.commit()

    r = await auth_client.get(f"/api/events/{event.id}")
    assert r.status_code == 200
    assert r.json()["message"] == "Test warning"


@pytest.mark.anyio
async def test_admin_list_all_events(admin_client, db_session):
    from tests.conftest import TEST_ADMIN_ID

    event = Event(
        event_type="admin_test",
        source="admin",
        user_id=TEST_ADMIN_ID,
        severity="info",
        message="Admin event",
    )
    db_session.add(event)
    await db_session.commit()

    r = await admin_client.get("/api/events/all")
    assert r.status_code == 200


# --- Suspend/Resume/Hibernate --------------------------------------------


@pytest.mark.anyio
async def test_suspend_vm(auth_client, db_session):
    vm_id = await _make_resource(db_session, "suspend-vm")
    r = await auth_client.post(
        f"/api/compute/vms/{vm_id}/action",
        json={"action": "suspend"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.anyio
async def test_hibernate_vm(auth_client, db_session):
    vm_id = await _make_resource(db_session, "hibernate-vm")
    r = await auth_client.post(
        f"/api/compute/vms/{vm_id}/action",
        json={"action": "hibernate"},
    )
    assert r.status_code == 200


@pytest.mark.anyio
async def test_resume_vm(auth_client, db_session):
    vm_id = await _make_resource(db_session, "resume-vm")
    r = await auth_client.post(
        f"/api/compute/vms/{vm_id}/action",
        json={"action": "resume"},
    )
    assert r.status_code == 200


# --- Object Copy/Move ----------------------------------------------------


async def _make_bucket(auth_client, name):
    r = await auth_client.post("/api/storage/buckets", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


@pytest.mark.anyio
async def test_copy_object(auth_client):
    bucket_id = await _make_bucket(auth_client, "copy-src-bkt")
    r = await auth_client.post(
        f"/api/storage/buckets/{bucket_id}/objects/copy",
        json={"source_key": "original.txt", "destination_key": "copy.txt"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "copied"


@pytest.mark.anyio
async def test_move_object(auth_client):
    bucket_id = await _make_bucket(auth_client, "move-src-bkt")
    r = await auth_client.post(
        f"/api/storage/buckets/{bucket_id}/objects/move",
        json={"source_key": "old.txt", "destination_key": "new.txt"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "moved"


@pytest.mark.anyio
async def test_copy_object_cross_bucket(auth_client):
    src_id = await _make_bucket(auth_client, "cross-src-bkt")
    dst_id = await _make_bucket(auth_client, "cross-dst-bkt")
    r = await auth_client.post(
        f"/api/storage/buckets/{src_id}/objects/copy",
        json={
            "source_key": "file.txt",
            "destination_key": "file.txt",
            "destination_bucket_id": dst_id,
        },
    )
    assert r.status_code == 200

"""Compute router tests - VMs and containers."""

import pytest
from sqlalchemy import select

from app.models.models import Resource, VMIDPool

# --- VM Tests ---


@pytest.mark.anyio
async def test_create_vm(auth_client, db_session):
    resp = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "test-vm",
            "template_vmid": 9000,
            "cores": 2,
            "memory_mb": 2048,
            "disk_gb": 32,
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["vmid"] == 1000  # first available (vmid_range_start default)
    assert data["status"] == "provisioning"
    assert "task" in data

    # Verify DB records
    result = await db_session.execute(select(Resource).where(Resource.display_name == "test-vm"))
    resource = result.scalar_one()
    assert resource.resource_type == "vm"
    assert resource.proxmox_vmid == 1000

    result = await db_session.execute(select(VMIDPool).where(VMIDPool.vmid == 1000))
    assert result.scalar_one() is not None


@pytest.mark.anyio
async def test_create_vm_unauthenticated(client):
    resp = await client.post(
        "/api/compute/vms",
        json={
            "name": "unauth-vm",
            "template_vmid": 9000,
        },
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_list_vms_empty(auth_client):
    resp = await auth_client.get("/api/compute/vms")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_list_vms_after_create(auth_client):
    await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "my-vm",
            "template_vmid": 9000,
        },
    )
    resp = await auth_client.get("/api/compute/vms")
    assert resp.status_code == 200
    vms = resp.json()
    assert len(vms) == 1
    assert vms[0]["name"] == "my-vm"
    assert vms[0]["live_status"] == "running"  # from mock


@pytest.mark.anyio
async def test_vm_action_start(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "action-vm",
            "template_vmid": 9000,
        },
    )
    vm_id = create.json()["id"]

    resp = await auth_client.post(f"/api/compute/vms/{vm_id}/action", json={"action": "start"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.anyio
async def test_vm_action_invalid(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "bad-action-vm",
            "template_vmid": 9000,
        },
    )
    vm_id = create.json()["id"]
    resp = await auth_client.post(f"/api/compute/vms/{vm_id}/action", json={"action": "explode"})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_delete_vm(auth_client, db_session):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "delete-me",
            "template_vmid": 9000,
        },
    )
    vm_id = create.json()["id"]

    resp = await auth_client.delete(f"/api/compute/vms/{vm_id}")
    assert resp.status_code == 202

    # Resource should be fully removed from DB
    db_session.expire_all()
    result = await db_session.execute(select(Resource).where(Resource.display_name == "delete-me"))
    r = result.scalar_one_or_none()
    assert r is None


@pytest.mark.anyio
async def test_vm_quota_exceeded(auth_client, db_session, test_user):
    """Default quota is 5 VMs; create 5, then fail on 6th."""
    for i in range(5):
        resp = await auth_client.post(
            "/api/compute/vms",
            json={
                "name": f"vm-{i}",
                "template_vmid": 9000,
            },
        )
        assert resp.status_code == 202

    resp = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "vm-overflow",
            "template_vmid": 9000,
        },
    )
    assert resp.status_code == 403
    assert "quota" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_vm_snapshots(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "snap-vm",
            "template_vmid": 9000,
        },
    )
    vm_id = create.json()["id"]

    # List snapshots
    resp = await auth_client.get(f"/api/compute/vms/{vm_id}/snapshots")
    assert resp.status_code == 200

    # Create snapshot
    resp = await auth_client.post(
        f"/api/compute/vms/{vm_id}/snapshots",
        json={
            "name": "snap1",
            "description": "test snapshot",
        },
    )
    assert resp.status_code == 200


# --- Container Tests ---


@pytest.mark.anyio
async def test_create_container(auth_client, db_session):
    resp = await auth_client.post(
        "/api/compute/containers",
        json={
            "name": "test-ct",
            "template": "local:vztmpl/ubuntu-22.04.tar.zst",
            "cores": 1,
            "memory_mb": 512,
            "disk_gb": 8,
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "provisioning"


@pytest.mark.anyio
async def test_list_containers_empty(auth_client):
    resp = await auth_client.get("/api/compute/containers")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_container_lifecycle(auth_client):
    create = await auth_client.post(
        "/api/compute/containers",
        json={
            "name": "lifecycle-ct",
            "template": "local:vztmpl/debian.tar.zst",
        },
    )
    ct_id = create.json()["id"]

    # Start
    resp = await auth_client.post(f"/api/compute/containers/{ct_id}/action", json={"action": "start"})
    assert resp.status_code == 200

    # Stop
    resp = await auth_client.post(f"/api/compute/containers/{ct_id}/action", json={"action": "stop"})
    assert resp.status_code == 200

    # Delete
    resp = await auth_client.delete(f"/api/compute/containers/{ct_id}")
    assert resp.status_code == 202


@pytest.mark.anyio
async def test_access_other_users_vm_denied(client, db_session, test_user, test_admin):
    """User cannot access another user's VM."""
    from tests.conftest import make_token

    admin_token = make_token(test_admin)
    user_token = make_token(test_user)

    # Admin creates a VM
    create = await client.post(
        "/api/compute/vms",
        json={"name": "admin-vm", "template_vmid": 9000},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    admin_vm_id = create.json()["id"]

    # Regular user tries to start it
    resp = await client.post(
        f"/api/compute/vms/{admin_vm_id}/action",
        json={"action": "start"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 404


# --- Termination Protection Tests ---


@pytest.mark.anyio
async def test_termination_protection_blocks_delete(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "protected-vm",
            "template_vmid": 9000,
            "termination_protected": True,
        },
    )
    vm_id = create.json()["id"]

    # Delete should be blocked
    resp = await auth_client.delete(f"/api/compute/vms/{vm_id}")
    assert resp.status_code == 403
    assert "termination protection" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_termination_protection_blocks_terminate_action(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "protected-vm2",
            "template_vmid": 9000,
            "termination_protected": True,
        },
    )
    vm_id = create.json()["id"]

    # Terminate action should also be blocked
    resp = await auth_client.post(f"/api/compute/vms/{vm_id}/action", json={"action": "terminate"})
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_toggle_termination_protection(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "toggle-protect-vm",
            "template_vmid": 9000,
            "termination_protected": True,
        },
    )
    vm_id = create.json()["id"]

    # Disable protection
    resp = await auth_client.patch(
        f"/api/compute/vms/{vm_id}/termination-protection",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["termination_protected"] is False

    # Now delete should work
    resp = await auth_client.delete(f"/api/compute/vms/{vm_id}")
    assert resp.status_code == 202


# --- Spec Validation Tests ---


@pytest.mark.anyio
async def test_vm_create_invalid_specs(auth_client):
    # RAM not multiple of 128
    resp = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "bad-spec-vm",
            "template_vmid": 9000,
            "cores": 2,
            "memory_mb": 100,
            "disk_gb": 32,
        },
    )
    assert resp.status_code == 422
    errors = resp.json()["detail"]
    assert any(e["field"] == "ram_mib" for e in errors)


@pytest.mark.anyio
async def test_vm_create_zero_cores(auth_client):
    resp = await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "zero-core-vm",
            "template_vmid": 9000,
            "cores": 0,
            "memory_mb": 2048,
            "disk_gb": 32,
        },
    )
    assert resp.status_code == 422


# --- Graceful vs Force Stop Tests ---


@pytest.mark.anyio
async def test_vm_stop_graceful(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={"name": "graceful-vm", "template_vmid": 9000},
    )
    vm_id = create.json()["id"]
    # Graceful stop (default, no force)
    resp = await auth_client.post(f"/api/compute/vms/{vm_id}/action", json={"action": "stop"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.anyio
async def test_vm_stop_forced(auth_client):
    create = await auth_client.post(
        "/api/compute/vms",
        json={"name": "force-vm", "template_vmid": 9000},
    )
    vm_id = create.json()["id"]
    # Forced stop
    resp = await auth_client.post(f"/api/compute/vms/{vm_id}/action", json={"action": "stop", "force": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- Instance Resize Tests ---


@pytest.mark.anyio
async def test_resize_vm_stopped(auth_client, db_session):
    create = await auth_client.post(
        "/api/compute/vms",
        json={"name": "resize-vm", "template_vmid": 9000},
    )
    vm_id = create.json()["id"]

    # Set resource status to stopped (required for resize)
    result = await db_session.execute(select(Resource).where(Resource.id == vm_id))
    resource = result.scalar_one()
    resource.status = "stopped"
    await db_session.commit()

    resp = await auth_client.patch(
        f"/api/compute/vms/{vm_id}/resize",
        json={"cores": 4, "memory_mb": 4096},
    )
    assert resp.status_code == 200
    assert resp.json()["specs"]["cores"] == 4
    assert resp.json()["specs"]["memory_mb"] == 4096


@pytest.mark.anyio
async def test_resize_vm_running_rejected(auth_client, db_session):
    create = await auth_client.post(
        "/api/compute/vms",
        json={"name": "resize-running-vm", "template_vmid": 9000},
    )
    vm_id = create.json()["id"]

    # Set resource status to running
    result = await db_session.execute(select(Resource).where(Resource.id == vm_id))
    resource = result.scalar_one()
    resource.status = "running"
    await db_session.commit()

    resp = await auth_client.patch(
        f"/api/compute/vms/{vm_id}/resize",
        json={"cores": 4},
    )
    assert resp.status_code == 409
    assert "stopped" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_resize_vm_invalid_specs(auth_client, db_session):
    create = await auth_client.post(
        "/api/compute/vms",
        json={"name": "resize-bad-vm", "template_vmid": 9000},
    )
    vm_id = create.json()["id"]

    result = await db_session.execute(select(Resource).where(Resource.id == vm_id))
    resource = result.scalar_one()
    resource.status = "stopped"
    await db_session.commit()

    resp = await auth_client.patch(
        f"/api/compute/vms/{vm_id}/resize",
        json={"memory_mb": 100},  # not multiple of 128
    )
    assert resp.status_code == 422


# --- Enhanced List Tests ---


@pytest.mark.anyio
async def test_list_vms_with_filters(auth_client):
    await auth_client.post("/api/compute/vms", json={"name": "alpha-vm", "template_vmid": 9000})
    await auth_client.post("/api/compute/vms", json={"name": "beta-vm", "template_vmid": 9000})

    resp = await auth_client.get("/api/compute/vms", params={"name_filter": "alpha"})
    assert resp.status_code == 200
    vms = resp.json()
    assert len(vms) == 1
    assert vms[0]["name"] == "alpha-vm"


@pytest.mark.anyio
async def test_list_vms_excludes_destroyed(auth_client):
    create = await auth_client.post("/api/compute/vms", json={"name": "soon-destroyed", "template_vmid": 9000})
    vm_id = create.json()["id"]
    await auth_client.delete(f"/api/compute/vms/{vm_id}")

    resp = await auth_client.get("/api/compute/vms")
    assert resp.status_code == 200
    assert not any(v["name"] == "soon-destroyed" for v in resp.json())


@pytest.mark.anyio
async def test_list_vms_enriched_data(auth_client):
    await auth_client.post("/api/compute/vms", json={"name": "enriched-vm", "template_vmid": 9000})
    resp = await auth_client.get("/api/compute/vms")
    assert resp.status_code == 200
    vm = resp.json()[0]
    assert "termination_protected" in vm
    assert "tags" in vm
    assert "live_status" in vm

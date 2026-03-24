"""Tests for console access and VM migration/export APIs."""

import json
import uuid

import pytest

from app.models.models import Resource
from tests.conftest import TEST_USER_ID

# --- Helpers -------------------------------------------------------------


async def _create_running_vm(auth_client, db_session, name="console-vm", status="running"):
    resource = Resource(
        id=uuid.uuid4(),
        owner_id=TEST_USER_ID,
        resource_type="vm",
        display_name=name,
        status=status,
        specs=json.dumps({"cpu": 2, "ram_mb": 2048, "disk_gb": 20}),
        proxmox_vmid=100 + hash(name) % 800,
        proxmox_node="node1",
    )
    db_session.add(resource)
    await db_session.commit()
    return str(resource.id)


# --- Console -------------------------------------------------------------


@pytest.mark.anyio
async def test_vnc_console(auth_client, db_session):
    vm_id = await _create_running_vm(auth_client, db_session)
    r = await auth_client.post(f"/api/console/{vm_id}/vnc")
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "vnc"
    assert "ticket" in data
    assert "websocket_url" in data


@pytest.mark.anyio
async def test_terminal_console(auth_client, db_session):
    vm_id = await _create_running_vm(auth_client, db_session, "term-vm")
    r = await auth_client.post(f"/api/console/{vm_id}/terminal")
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "terminal"
    assert "ticket" in data


@pytest.mark.anyio
async def test_spice_console(auth_client, db_session):
    vm_id = await _create_running_vm(auth_client, db_session, "spice-vm")
    r = await auth_client.post(f"/api/console/{vm_id}/spice")
    assert r.status_code == 200
    assert r.json()["type"] == "spice"


@pytest.mark.anyio
async def test_available_consoles(auth_client, db_session):
    vm_id = await _create_running_vm(auth_client, db_session, "avail-vm")
    r = await auth_client.get(f"/api/console/{vm_id}/available")
    assert r.status_code == 200
    assert "vnc" in r.json()["available"]
    assert "terminal" in r.json()["available"]


@pytest.mark.anyio
async def test_console_not_found(auth_client):
    r = await auth_client.post(f"/api/console/{uuid.uuid4()}/vnc")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_console_not_running(auth_client, db_session):
    """Console should require running state."""
    vm_id = await _create_running_vm(auth_client, db_session, "stopped-vm", status="stopped")
    r = await auth_client.post(f"/api/console/{vm_id}/vnc")
    assert r.status_code == 409


# --- Migration/Export ----------------------------------------------------


@pytest.mark.anyio
async def test_export_vm(auth_client, db_session):
    vm_id = await _create_running_vm(auth_client, db_session, "export-vm")
    r = await auth_client.post(
        f"/api/migration/{vm_id}/export",
        json={"storage": "local", "compress": "zstd", "mode": "snapshot"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "export_started"
    assert "task_id" in data


@pytest.mark.anyio
async def test_export_invalid_compress(auth_client, db_session):
    vm_id = await _create_running_vm(auth_client, db_session, "export-bad")
    r = await auth_client.post(
        f"/api/migration/{vm_id}/export",
        json={"compress": "bzip2"},
    )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_clone_vm(auth_client, db_session):
    vm_id = await _create_running_vm(auth_client, db_session, "clone-src")
    r = await auth_client.post(
        f"/api/migration/{vm_id}/clone",
        json={"name": "clone-target"},
    )
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "clone_started"
    assert "new_id" in data
    assert "new_vmid" in data


@pytest.mark.anyio
async def test_convert_to_template(auth_client, db_session):
    """Convert a stopped VM to template."""
    vm_id = await _create_running_vm(auth_client, db_session, "tpl-vm", status="stopped")
    r = await auth_client.post(f"/api/migration/{vm_id}/convert-template")
    assert r.status_code == 200
    assert r.json()["status"] == "converted"


@pytest.mark.anyio
async def test_convert_running_vm_fails(auth_client, db_session):
    vm_id = await _create_running_vm(auth_client, db_session, "convert-fail")
    r = await auth_client.post(f"/api/migration/{vm_id}/convert-template")
    assert r.status_code == 409


@pytest.mark.anyio
async def test_export_status(auth_client, db_session):
    vm_id = await _create_running_vm(auth_client, db_session, "status-vm")
    r = await auth_client.get(
        f"/api/migration/{vm_id}/export-status",
        params={"task_id": "UPID:node1:00001234:00000001:00000000:vzdump::root@pam:"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "OK"

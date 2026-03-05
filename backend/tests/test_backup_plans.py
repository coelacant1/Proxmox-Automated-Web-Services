"""Backup and backup plan API tests."""

import pytest
from sqlalchemy import select

from app.models.models import Backup, BackupPlan


@pytest.mark.anyio
async def test_list_backups_empty(auth_client):
    resp = await auth_client.get("/api/backups")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_create_backup(auth_client):
    # Create a VM first
    vm = await auth_client.post("/api/compute/vms", json={"name": "backup-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    resp = await auth_client.post("/api/backups", json={"resource_id": vm_id, "notes": "test backup"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"
    assert resp.json()["backup_type"] == "snapshot"


@pytest.mark.anyio
async def test_list_backups_for_resource(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "filter-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    await auth_client.post("/api/backups", json={"resource_id": vm_id})

    resp = await auth_client.get("/api/backups", params={"resource_id": vm_id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.anyio
async def test_delete_backup(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "del-backup-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]
    backup = await auth_client.post("/api/backups", json={"resource_id": vm_id})
    backup_id = backup.json()["id"]

    resp = await auth_client.delete(f"/api/backups/{backup_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


# --- Backup Plans ---


@pytest.mark.anyio
async def test_list_backup_plans_empty(auth_client):
    resp = await auth_client.get("/api/backups/plans")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_create_backup_plan(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "plan-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    resp = await auth_client.post(
        "/api/backups/plans",
        json={
            "resource_id": vm_id,
            "name": "Daily Backup",
            "schedule_cron": "0 2 * * *",
            "retention_count": 7,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Daily Backup"


@pytest.mark.anyio
async def test_update_backup_plan(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "update-plan-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]
    plan = await auth_client.post(
        "/api/backups/plans",
        json={"resource_id": vm_id, "name": "Weekly", "schedule_cron": "0 3 * * 0"},
    )
    plan_id = plan.json()["id"]

    resp = await auth_client.patch(f"/api/backups/plans/{plan_id}", json={"name": "Monthly", "is_active": False})
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_delete_backup_plan(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "del-plan-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]
    plan = await auth_client.post(
        "/api/backups/plans",
        json={"resource_id": vm_id, "name": "Temp", "schedule_cron": "0 0 * * *"},
    )
    plan_id = plan.json()["id"]

    resp = await auth_client.delete(f"/api/backups/plans/{plan_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

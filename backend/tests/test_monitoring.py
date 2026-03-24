"""Tests for monitoring metrics and alarms API."""

import uuid

import pytest

# --- Helpers ---


async def _create_vm(auth_client):
    r = await auth_client.post("/api/compute/vms", json={"name": "metrics-vm", "template_vmid": 9000})
    assert r.status_code == 202
    return r.json()["id"]


# --- Metrics ---


@pytest.mark.anyio
async def test_get_current_metrics(auth_client):
    vm_id = await _create_vm(auth_client)
    r = await auth_client.get(f"/api/monitoring/metrics/{vm_id}/current")
    assert r.status_code == 200
    data = r.json()
    assert data["resource_id"] == vm_id
    assert "cpu" in data
    assert "memory" in data
    assert "network" in data


@pytest.mark.anyio
async def test_get_rrd_metrics(auth_client):
    vm_id = await _create_vm(auth_client)
    r = await auth_client.get(f"/api/monitoring/metrics/{vm_id}?timeframe=hour")
    assert r.status_code == 200
    data = r.json()
    assert data["timeframe"] == "hour"
    assert isinstance(data["data"], list)


@pytest.mark.anyio
async def test_get_metrics_invalid_timeframe(auth_client):
    vm_id = await _create_vm(auth_client)
    r = await auth_client.get(f"/api/monitoring/metrics/{vm_id}?timeframe=century")
    assert r.status_code == 400


@pytest.mark.anyio
async def test_get_metrics_not_found(auth_client):
    r = await auth_client.get(f"/api/monitoring/metrics/{uuid.uuid4()}/current")
    assert r.status_code == 404


# --- Alarms ---


@pytest.mark.anyio
async def test_create_alarm(auth_client):
    vm_id = await _create_vm(auth_client)
    r = await auth_client.post(
        "/api/monitoring/alarms",
        json={
            "resource_id": vm_id,
            "name": "High CPU",
            "metric": "cpu",
            "comparison": "gt",
            "threshold": 80.0,
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "High CPU"
    assert data["state"] == "ok"
    assert data["metric"] == "cpu"


@pytest.mark.anyio
async def test_create_alarm_invalid_metric(auth_client):
    vm_id = await _create_vm(auth_client)
    r = await auth_client.post(
        "/api/monitoring/alarms",
        json={
            "resource_id": vm_id,
            "name": "Bad",
            "metric": "temperature",
            "comparison": "gt",
            "threshold": 80.0,
        },
    )
    assert r.status_code == 422


@pytest.mark.anyio
async def test_list_alarms(auth_client):
    vm_id = await _create_vm(auth_client)
    await auth_client.post(
        "/api/monitoring/alarms",
        json={
            "resource_id": vm_id,
            "name": "Disk Alert",
            "metric": "disk",
            "comparison": "gt",
            "threshold": 90.0,
        },
    )
    r = await auth_client.get("/api/monitoring/alarms")
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.anyio
async def test_list_alarms_filter_by_resource(auth_client):
    vm_id = await _create_vm(auth_client)
    await auth_client.post(
        "/api/monitoring/alarms",
        json={
            "resource_id": vm_id,
            "name": "Net Alert",
            "metric": "netin",
            "comparison": "gt",
            "threshold": 1000000,
        },
    )
    r = await auth_client.get(f"/api/monitoring/alarms?resource_id={vm_id}")
    assert r.status_code == 200
    for alarm in r.json():
        assert alarm["resource_id"] == vm_id


@pytest.mark.anyio
async def test_get_alarm(auth_client):
    vm_id = await _create_vm(auth_client)
    cr = await auth_client.post(
        "/api/monitoring/alarms",
        json={
            "resource_id": vm_id,
            "name": "Mem Alert",
            "metric": "memory",
            "comparison": "gte",
            "threshold": 95.0,
        },
    )
    alarm_id = cr.json()["id"]
    r = await auth_client.get(f"/api/monitoring/alarms/{alarm_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Mem Alert"


@pytest.mark.anyio
async def test_update_alarm(auth_client):
    vm_id = await _create_vm(auth_client)
    cr = await auth_client.post(
        "/api/monitoring/alarms",
        json={
            "resource_id": vm_id,
            "name": "CPU Alert",
            "metric": "cpu",
            "comparison": "gt",
            "threshold": 70.0,
        },
    )
    alarm_id = cr.json()["id"]
    r = await auth_client.patch(
        f"/api/monitoring/alarms/{alarm_id}",
        json={"threshold": 85.0, "is_active": False},
    )
    assert r.status_code == 200


@pytest.mark.anyio
async def test_delete_alarm(auth_client):
    vm_id = await _create_vm(auth_client)
    cr = await auth_client.post(
        "/api/monitoring/alarms",
        json={
            "resource_id": vm_id,
            "name": "Temp Alert",
            "metric": "cpu",
            "comparison": "lt",
            "threshold": 10.0,
        },
    )
    alarm_id = cr.json()["id"]
    r = await auth_client.delete(f"/api/monitoring/alarms/{alarm_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"


@pytest.mark.anyio
async def test_alarm_not_found(auth_client):
    r = await auth_client.get(f"/api/monitoring/alarms/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_create_alarm_wrong_resource(auth_client):
    """Alarm creation fails if resource doesn't belong to user."""
    r = await auth_client.post(
        "/api/monitoring/alarms",
        json={
            "resource_id": str(uuid.uuid4()),
            "name": "Ghost",
            "metric": "cpu",
            "comparison": "gt",
            "threshold": 50.0,
        },
    )
    assert r.status_code == 404

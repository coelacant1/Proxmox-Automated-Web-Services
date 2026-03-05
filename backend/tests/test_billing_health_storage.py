"""Tests for billing, health check, and extended storage APIs."""

import json
import uuid

import pytest

from app.models.models import Resource
from tests.conftest import TEST_USER_ID


async def _make_resource(db_session, name="billing-vm", status="running"):
    r = Resource(
        id=uuid.uuid4(),
        owner_id=TEST_USER_ID,
        resource_type="vm",
        display_name=name,
        status=status,
        specs=json.dumps({"cpu": 2, "ram_mb": 2048, "disk_gb": 20}),
        proxmox_vmid=300 + hash(name) % 600,
        proxmox_node="node1",
    )
    db_session.add(r)
    await db_session.commit()
    return str(r.id)


# --- Billing --------------------------------------------------------------


@pytest.mark.anyio
async def test_list_cost_rates(auth_client):
    r = await auth_client.get("/api/billing/rates")
    assert r.status_code == 200
    assert len(r.json()) > 0


@pytest.mark.anyio
async def test_billing_estimate(auth_client, db_session):
    await _make_resource(db_session, "bill-vm")
    r = await auth_client.get("/api/billing/estimate")
    assert r.status_code == 200
    data = r.json()
    assert "total_monthly_estimate" in data
    assert data["currency"] == "USD"
    assert data["resource_count"] >= 1


@pytest.mark.anyio
async def test_set_cost_rate_admin(admin_client):
    r = await admin_client.put(
        "/api/billing/rates",
        json={"resource_type": "vm", "metric": "cpu_hour", "rate": 0.02},
    )
    assert r.status_code == 200


@pytest.mark.anyio
async def test_set_cost_rate_non_admin(auth_client):
    r = await auth_client.put(
        "/api/billing/rates",
        json={"resource_type": "vm", "metric": "cpu_hour", "rate": 0.02},
    )
    assert r.status_code == 403


# --- Health Checks --------------------------------------------------------


@pytest.mark.anyio
async def test_run_health_check(auth_client, db_session):
    vm_id = await _make_resource(db_session, "health-vm")
    r = await auth_client.post(f"/api/health/{vm_id}/check")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert "check_id" in data


@pytest.mark.anyio
async def test_get_health_history(auth_client, db_session):
    vm_id = await _make_resource(db_session, "health-hist")
    await auth_client.post(f"/api/health/{vm_id}/check")
    r = await auth_client.get(f"/api/health/{vm_id}")
    assert r.status_code == 200
    assert len(r.json()["checks"]) >= 1


@pytest.mark.anyio
async def test_guest_agent_info(auth_client, db_session):
    vm_id = await _make_resource(db_session, "agent-vm")
    r = await auth_client.get(f"/api/health/{vm_id}/agent")
    assert r.status_code == 200
    assert r.json()["agent_available"] is True


@pytest.mark.anyio
async def test_health_not_found(auth_client):
    r = await auth_client.get(f"/api/health/{uuid.uuid4()}")
    assert r.status_code == 404


# --- Storage Extensions --------------------------------------------------


async def _make_bucket(auth_client, name="ext-test-bucket"):
    r = await auth_client.post("/api/storage/buckets", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


@pytest.mark.anyio
async def test_set_bucket_policy(auth_client):
    bucket_id = await _make_bucket(auth_client, "policy-test-bkt")
    r = await auth_client.put(
        f"/api/storage/buckets/{bucket_id}/policy",
        json={"policy": {"Version": "2012-10-17", "Statement": []}},
    )
    assert r.status_code == 200


@pytest.mark.anyio
async def test_get_bucket_policy(auth_client):
    bucket_id = await _make_bucket(auth_client, "get-policy-bkt")
    await auth_client.put(
        f"/api/storage/buckets/{bucket_id}/policy",
        json={"policy": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow"}]}},
    )
    r = await auth_client.get(f"/api/storage/buckets/{bucket_id}/policy")
    assert r.status_code == 200
    assert r.json()["policy"]["Statement"][0]["Effect"] == "Allow"


@pytest.mark.anyio
async def test_delete_bucket_policy(auth_client):
    bucket_id = await _make_bucket(auth_client, "del-policy-bkt")
    await auth_client.put(
        f"/api/storage/buckets/{bucket_id}/policy",
        json={"policy": {"test": True}},
    )
    r = await auth_client.delete(f"/api/storage/buckets/{bucket_id}/policy")
    assert r.status_code == 200


@pytest.mark.anyio
async def test_set_bucket_encryption(auth_client):
    bucket_id = await _make_bucket(auth_client, "encrypt-bkt")
    r = await auth_client.put(
        f"/api/storage/buckets/{bucket_id}/encryption",
        json={"algorithm": "AES256"},
    )
    assert r.status_code == 200
    assert r.json()["algorithm"] == "AES256"


@pytest.mark.anyio
async def test_get_bucket_encryption(auth_client):
    bucket_id = await _make_bucket(auth_client, "get-enc-bkt")
    await auth_client.put(
        f"/api/storage/buckets/{bucket_id}/encryption",
        json={"algorithm": "AES256"},
    )
    r = await auth_client.get(f"/api/storage/buckets/{bucket_id}/encryption")
    assert r.status_code == 200
    assert r.json()["encryption_enabled"] is True


@pytest.mark.anyio
async def test_bucket_metrics(auth_client):
    bucket_id = await _make_bucket(auth_client, "metrics-bkt")
    r = await auth_client.get(f"/api/storage/buckets/{bucket_id}/metrics")
    assert r.status_code == 200
    data = r.json()
    assert "size_bytes" in data
    assert "quota_max_gb" in data


@pytest.mark.anyio
async def test_create_folder(auth_client):
    bucket_id = await _make_bucket(auth_client, "folder-bkt")
    r = await auth_client.put(f"/api/storage/buckets/{bucket_id}/folders/documents/reports")
    assert r.status_code == 200
    assert r.json()["folder"] == "documents/reports/"

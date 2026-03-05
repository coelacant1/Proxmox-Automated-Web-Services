"""Tests for object metadata, bucket sharing, bucket detail, custom metrics,
ingress config, billing detail, and backup browser APIs."""

import json
import uuid

import pytest

from app.models.models import Backup, BackupPlan, CustomMetric, Resource
from tests.conftest import TEST_USER_ID


async def _make_resource(db_session, name="api-vm", status="running"):
    r = Resource(
        id=uuid.uuid4(),
        owner_id=TEST_USER_ID,
        resource_type="vm",
        display_name=name,
        status=status,
        specs=json.dumps({"cpu": 2, "ram_mb": 2048, "disk_gb": 20}),
        proxmox_vmid=600 + hash(name) % 300,
        proxmox_node="node1",
    )
    db_session.add(r)
    await db_session.commit()
    return str(r.id)


async def _make_bucket(auth_client, name):
    r = await auth_client.post("/api/storage/buckets", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


# --- Object Metadata -----------------------------------------------------


@pytest.mark.anyio
async def test_set_and_get_object_metadata(auth_client):
    bucket_id = await _make_bucket(auth_client, "meta-bkt-1")

    r = await auth_client.put(
        f"/api/storage/buckets/{bucket_id}/objects/doc.txt/metadata",
        json={"metadata": {"content-type": "text/plain", "author": "test"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "updated"

    r2 = await auth_client.get(f"/api/storage/buckets/{bucket_id}/objects/doc.txt/metadata")
    assert r2.status_code == 200
    assert r2.json()["metadata"]["author"] == "test"


@pytest.mark.anyio
async def test_object_metadata_size_limit(auth_client):
    bucket_id = await _make_bucket(auth_client, "meta-bkt-2")
    big_meta = {f"key{i}": "x" * 100 for i in range(30)}
    r = await auth_client.put(
        f"/api/storage/buckets/{bucket_id}/objects/big.txt/metadata",
        json={"metadata": big_meta},
    )
    assert r.status_code == 400
    assert "2KB" in r.json()["detail"]


# --- Bucket Detail & Settings --------------------------------------------


@pytest.mark.anyio
async def test_bucket_detail(auth_client):
    bucket_id = await _make_bucket(auth_client, "detail-bkt")
    r = await auth_client.get(f"/api/storage/buckets/{bucket_id}/detail")
    assert r.status_code == 200
    assert r.json()["name"] == "detail-bkt"
    assert "policy" in r.json()
    assert "encryption" in r.json()


@pytest.mark.anyio
async def test_update_bucket_settings(auth_client):
    bucket_id = await _make_bucket(auth_client, "settings-bkt")
    r = await auth_client.patch(
        f"/api/storage/buckets/{bucket_id}/settings",
        json={"description": "My test bucket", "max_size_gib": 10.5, "tags": {"env": "dev"}},
    )
    assert r.status_code == 200

    r2 = await auth_client.get(f"/api/storage/buckets/{bucket_id}/detail")
    assert r2.json()["description"] == "My test bucket"
    assert r2.json()["user_tags"]["env"] == "dev"


# --- Bucket Sharing ------------------------------------------------------


@pytest.mark.anyio
async def test_share_and_list_shares(auth_client):
    bucket_id = await _make_bucket(auth_client, "share-bkt")
    target_id = str(uuid.uuid4())

    r = await auth_client.post(
        f"/api/storage/buckets/{bucket_id}/shares",
        json={"target_user_id": target_id, "permission": "write"},
    )
    assert r.status_code == 200
    assert r.json()["permission"] == "write"

    r2 = await auth_client.get(f"/api/storage/buckets/{bucket_id}/shares")
    assert r2.status_code == 200
    assert len(r2.json()) == 1
    assert r2.json()[0]["user_id"] == target_id


@pytest.mark.anyio
async def test_revoke_share(auth_client):
    bucket_id = await _make_bucket(auth_client, "revoke-bkt")
    target_id = str(uuid.uuid4())

    await auth_client.post(
        f"/api/storage/buckets/{bucket_id}/shares",
        json={"target_user_id": target_id},
    )
    r = await auth_client.delete(f"/api/storage/buckets/{bucket_id}/shares/{target_id}")
    assert r.status_code == 200

    r2 = await auth_client.get(f"/api/storage/buckets/{bucket_id}/shares")
    assert len(r2.json()) == 0


@pytest.mark.anyio
async def test_shared_with_me(auth_client):
    r = await auth_client.get("/api/storage/shared-with-me")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# --- Custom Metrics ------------------------------------------------------


@pytest.mark.anyio
async def test_push_custom_metric(auth_client):
    r = await auth_client.post(
        "/api/monitoring/custom-metrics",
        json={"namespace": "app/web", "metric_name": "request_count", "value": 42.0, "unit": "Count"},
    )
    assert r.status_code == 201
    assert r.json()["status"] == "created"


@pytest.mark.anyio
async def test_push_custom_metrics_batch(auth_client):
    r = await auth_client.post(
        "/api/monitoring/custom-metrics/batch",
        json={
            "metrics": [
                {"namespace": "app/web", "metric_name": "latency", "value": 120.5, "unit": "ms"},
                {"namespace": "app/web", "metric_name": "errors", "value": 3.0, "unit": "Count"},
            ]
        },
    )
    assert r.status_code == 201
    assert r.json()["count"] == 2


@pytest.mark.anyio
async def test_list_custom_metrics(auth_client):
    await auth_client.post(
        "/api/monitoring/custom-metrics",
        json={"namespace": "test/ns", "metric_name": "cpu_custom", "value": 55.0},
    )
    r = await auth_client.get("/api/monitoring/custom-metrics?namespace=test/ns")
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert r.json()[0]["namespace"] == "test/ns"


@pytest.mark.anyio
async def test_batch_too_many_metrics(auth_client):
    metrics = [{"namespace": "x", "metric_name": f"m{i}", "value": float(i)} for i in range(26)]
    r = await auth_client.post("/api/monitoring/custom-metrics/batch", json={"metrics": metrics})
    assert r.status_code == 400


# --- Ingress Config ------------------------------------------------------


@pytest.mark.anyio
async def test_get_ingress_config(auth_client):
    r = await auth_client.get("/api/endpoints/ingress-config")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


# --- Billing Detail ------------------------------------------------------


@pytest.mark.anyio
async def test_billing_resource_cost(auth_client, db_session):
    vm_id = await _make_resource(db_session, "billing-vm")
    r = await auth_client.get(f"/api/billing/resources/{vm_id}")
    assert r.status_code == 200
    assert "breakdown" in r.json()
    assert r.json()["breakdown"]["cpu"]["units"] == 2


@pytest.mark.anyio
async def test_billing_summary(auth_client, db_session):
    await _make_resource(db_session, "summary-vm-1")
    await _make_resource(db_session, "summary-vm-2")
    r = await auth_client.get("/api/billing/summary")
    assert r.status_code == 200
    assert "by_type" in r.json()
    assert r.json()["resource_count"] >= 2


# --- Backup Browser & Notifications --------------------------------------


@pytest.mark.anyio
async def test_backup_contents(auth_client, db_session):
    vm_id = await _make_resource(db_session, "backup-browse-vm")
    backup = Backup(
        id=uuid.uuid4(),
        resource_id=uuid.UUID(vm_id),
        owner_id=TEST_USER_ID,
        backup_type="snapshot",
        status="completed",
    )
    db_session.add(backup)
    await db_session.commit()

    r = await auth_client.get(f"/api/backups/{backup.id}/contents")
    assert r.status_code == 200
    assert "contents" in r.json()


@pytest.mark.anyio
async def test_backup_notifications_crud(auth_client, db_session):
    vm_id = await _make_resource(db_session, "backup-notif-vm")
    plan = BackupPlan(
        id=uuid.uuid4(),
        resource_id=uuid.UUID(vm_id),
        owner_id=TEST_USER_ID,
        name="test-plan",
        schedule_cron="0 2 * * *",
        backup_type="snapshot",
        retention_count=7,
        retention_days=30,
    )
    db_session.add(plan)
    await db_session.commit()

    r = await auth_client.put(
        f"/api/backups/{plan.id}/notifications",
        json={"enabled": True, "webhook_url": "https://hooks.example.com/backup"},
    )
    assert r.status_code == 200
    assert r.json()["notifications"]["webhook_url"] == "https://hooks.example.com/backup"

    r2 = await auth_client.get(f"/api/backups/{plan.id}/notifications")
    assert r2.status_code == 200
    assert r2.json()["notification_enabled"] is True

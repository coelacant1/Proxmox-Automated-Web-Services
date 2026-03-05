"""Tests for admin features, search, billing quota, endpoint validation,
metrics keys, VPC instances, webhook delivery, and health detail."""

import pytest


# --- Global Search --------------------------------------------------------


@pytest.mark.anyio
async def test_global_search(auth_client):
    r = await auth_client.get("/api/search/?q=test")
    assert r.status_code == 200
    data = r.json()
    assert "resources" in data["results"]
    assert "templates" in data["results"]
    assert "total" in data


@pytest.mark.anyio
async def test_global_search_empty(auth_client):
    r = await auth_client.get("/api/search/?q=zzz_nonexistent_zzz")
    assert r.status_code == 200
    assert r.json()["total"] == 0


# --- Health Detailed ------------------------------------------------------


@pytest.mark.anyio
async def test_health_basic(auth_client):
    r = await auth_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


@pytest.mark.anyio
async def test_health_detailed_admin(admin_client):
    r = await admin_client.get("/health/detailed")
    assert r.status_code == 200
    data = r.json()
    assert "subsystems" in data
    assert "database" in data["subsystems"]


@pytest.mark.anyio
async def test_health_detailed_non_admin(auth_client):
    r = await auth_client.get("/health/detailed")
    assert r.status_code == 403


# --- Custom Metrics Keys -------------------------------------------------


@pytest.mark.anyio
async def test_create_metrics_key(auth_client):
    r = await auth_client.post("/api/monitoring/metrics-keys?label=test-key")
    assert r.status_code == 201
    assert r.json()["key"].startswith("paws_mk_")


@pytest.mark.anyio
async def test_list_metrics_keys(auth_client):
    await auth_client.post("/api/monitoring/metrics-keys?label=list-key")
    r = await auth_client.get("/api/monitoring/metrics-keys")
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.anyio
async def test_delete_metrics_key(auth_client):
    cr = await auth_client.post("/api/monitoring/metrics-keys?label=del-key")
    key = cr.json()["key"]
    prefix = key[:12]
    r = await auth_client.delete(f"/api/monitoring/metrics-keys/{prefix}")
    assert r.status_code == 200


# --- Endpoint Validation -------------------------------------------------


@pytest.mark.anyio
async def test_validate_subdomain_valid(auth_client):
    r = await auth_client.get("/api/endpoints/validate-subdomain/my-app")
    assert r.status_code == 200
    assert r.json()["valid"] is True


@pytest.mark.anyio
async def test_validate_subdomain_reserved(auth_client):
    r = await auth_client.get("/api/endpoints/validate-subdomain/admin")
    assert r.status_code == 200
    assert r.json()["valid"] is False
    assert len(r.json()["errors"]) >= 1


@pytest.mark.anyio
async def test_validate_subdomain_invalid_format(auth_client):
    r = await auth_client.get("/api/endpoints/validate-subdomain/INVALID_FORMAT!")
    assert r.status_code == 200
    assert r.json()["valid"] is False


# --- Billing Quota Status ------------------------------------------------


@pytest.mark.anyio
async def test_billing_quota_status(auth_client):
    r = await auth_client.get("/api/billing/quota-status")
    assert r.status_code == 200
    data = r.json()
    assert "monthly_credits" in data
    assert "usage_percent" in data
    assert "remaining" in data


# --- Admin Tag Policies --------------------------------------------------


@pytest.mark.anyio
async def test_create_tag_policy(admin_client):
    r = await admin_client.post(
        "/api/admin/users/tag-policies",
        json={"key": "env", "required": True, "allowed_values": ["prod", "dev", "staging"]},
    )
    assert r.status_code == 201
    assert r.json()["required"] is True


@pytest.mark.anyio
async def test_list_tag_policies(admin_client):
    await admin_client.post("/api/admin/users/tag-policies", json={"key": "team"})
    r = await admin_client.get("/api/admin/users/tag-policies")
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.anyio
async def test_delete_tag_policy(admin_client):
    await admin_client.post("/api/admin/users/tag-policies", json={"key": "delete-me"})
    r = await admin_client.delete("/api/admin/users/tag-policies/delete-me")
    assert r.status_code == 200


# --- Admin Node Affinity -------------------------------------------------


@pytest.mark.anyio
async def test_create_node_affinity(admin_client):
    r = await admin_client.post(
        "/api/admin/users/node-affinity",
        json={"target_id": "user-1", "target_type": "user", "node": "pve1"},
    )
    assert r.status_code == 201
    assert r.json()["node"] == "pve1"


@pytest.mark.anyio
async def test_list_node_affinity(admin_client):
    await admin_client.post(
        "/api/admin/users/node-affinity",
        json={"target_id": "user-2", "node": "pve2"},
    )
    r = await admin_client.get("/api/admin/users/node-affinity")
    assert r.status_code == 200
    assert len(r.json()) >= 1


# --- Admin Restore Testing -----------------------------------------------


@pytest.mark.anyio
async def test_admin_test_restore(admin_client):
    r = await admin_client.post("/api/admin/users/backups/test-123/test-restore")
    assert r.status_code == 200
    assert r.json()["status"] == "test_scheduled"


# --- Admin MFA Controls --------------------------------------------------


@pytest.mark.anyio
async def test_admin_mfa_status(admin_client):
    r = await admin_client.get("/api/admin/users/mfa/status")
    assert r.status_code == 200
    assert len(r.json()) >= 1


# --- VPC Instance Listing ------------------------------------------------


@pytest.mark.anyio
async def test_vpc_instances_empty(auth_client, db_session):
    """Create a VPC and verify instance listing returns empty."""
    from app.models.models import VPC

    from tests.conftest import TEST_USER_ID

    vpc = VPC(owner_id=TEST_USER_ID, name="inst-vpc", cidr="10.10.0.0/16")
    db_session.add(vpc)
    await db_session.commit()
    await db_session.refresh(vpc)

    r = await auth_client.get(f"/api/vpcs/{vpc.id}/instances")
    assert r.status_code == 200
    assert r.json() == []


# --- Webhook Delivery Service --------------------------------------------


@pytest.mark.anyio
async def test_webhook_delivery():
    from app.services.webhook_delivery import deliver_webhook, get_delivery_log

    result = await deliver_webhook(
        "https://example.com/hook",
        "test.event",
        {"data": "test"},
    )
    assert result["status"] == "delivered"

    log = get_delivery_log()
    assert len(log) >= 1


@pytest.mark.anyio
async def test_webhook_delivery_ssrf_blocked():
    from app.services.webhook_delivery import deliver_webhook

    result = await deliver_webhook(
        "https://192.168.1.1/hook",
        "test.event",
        {"data": "test"},
    )
    assert result["status"] == "rejected"

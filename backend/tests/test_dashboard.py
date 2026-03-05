"""Dashboard router tests."""

import pytest


@pytest.mark.anyio
async def test_dashboard_summary(auth_client):
    resp = await auth_client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "resources" in data
    assert "quota" in data
    assert "recent_activity" in data
    assert data["resources"]["vms"] == 0


@pytest.mark.anyio
async def test_dashboard_summary_unauthenticated(client):
    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_dashboard_summary_with_resources(auth_client):
    # Create a VM so summary includes it
    await auth_client.post(
        "/api/compute/vms",
        json={
            "name": "dash-vm",
            "template_vmid": 9000,
        },
    )
    resp = await auth_client.get("/api/dashboard/summary")
    data = resp.json()
    assert data["resources"]["vms"] == 1


@pytest.mark.anyio
async def test_admin_overview(admin_client):
    resp = await admin_client.get("/api/dashboard/admin/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_users" in data
    assert "total_resources" in data


@pytest.mark.anyio
async def test_admin_overview_denied_for_user(auth_client):
    resp = await auth_client.get("/api/dashboard/admin/overview")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_usage_history(auth_client):
    resp = await auth_client.get("/api/dashboard/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert "resource_count" in data

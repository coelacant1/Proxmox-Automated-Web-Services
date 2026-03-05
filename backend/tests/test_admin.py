"""Admin router tests."""

import pytest


@pytest.mark.anyio
async def test_admin_list_users(admin_client, test_user, test_admin):
    resp = await admin_client.get("/api/admin/users/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    assert len(data["items"]) >= 2


@pytest.mark.anyio
async def test_admin_list_users_denied_for_regular_user(auth_client):
    resp = await auth_client.get("/api/admin/users/")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_admin_user_count(admin_client, test_user, test_admin):
    resp = await admin_client.get("/api/admin/users/count")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 2


@pytest.mark.anyio
async def test_admin_update_user_role(admin_client, test_user):
    resp = await admin_client.patch(
        f"/api/admin/users/{test_user.id}/role",
        params={"role": "viewer"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["admin", "operator", "member", "viewer"])
async def test_admin_update_user_role_all_valid(admin_client, test_user, role):
    resp = await admin_client.patch(
        f"/api/admin/users/{test_user.id}/role",
        params={"role": role},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == role


@pytest.mark.anyio
async def test_admin_update_user_role_invalid(admin_client, test_user):
    resp = await admin_client.patch(
        f"/api/admin/users/{test_user.id}/role",
        params={"role": "superadmin"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_admin_set_quota(admin_client, test_user):
    resp = await admin_client.put(
        f"/api/admin/users/{test_user.id}/quota",
        json={
            "max_vms": 20,
            "max_containers": 50,
            "max_vcpus": 64,
            "max_ram_mb": 131072,
            "max_disk_gb": 2000,
            "max_snapshots": 100,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_vms"] == 20


@pytest.mark.anyio
async def test_admin_get_quota(admin_client, test_user):
    resp = await admin_client.get(f"/api/admin/users/{test_user.id}/quota")
    assert resp.status_code == 200
    assert "max_vms" in resp.json()


@pytest.mark.anyio
async def test_admin_deactivate_user(admin_client, test_user):
    resp = await admin_client.patch(
        f"/api/admin/users/{test_user.id}/active",
        params={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

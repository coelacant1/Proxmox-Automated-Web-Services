"""Tests for Phase 9 API endpoints: templates, quota requests, settings, admin enhancements."""


import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AuditLog, QuotaRequest, SystemSetting, TemplateCatalog, User

# ---------------------------------------------------------------------------
# Admin Template Catalog API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_create_template(admin_client: AsyncClient):
    resp = await admin_client.post(
        "/api/admin/templates/",
        json={
            "proxmox_vmid": 9000,
            "name": "Ubuntu 22.04",
            "description": "Standard Ubuntu LTS",
            "os_type": "linux",
            "category": "vm",
            "min_cpu": 2,
            "min_ram_mb": 2048,
            "min_disk_gb": 20,
            "tags": ["linux", "ubuntu"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Ubuntu 22.04"
    assert data["tags"] == ["linux", "ubuntu"]
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_admin_create_duplicate_vmid(admin_client: AsyncClient, db_session: AsyncSession):
    db_session.add(TemplateCatalog(proxmox_vmid=9001, name="Existing", category="vm"))
    await db_session.commit()

    resp = await admin_client.post(
        "/api/admin/templates/",
        json={"proxmox_vmid": 9001, "name": "Duplicate", "category": "vm"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_admin_list_templates(admin_client: AsyncClient, db_session: AsyncSession):
    db_session.add(TemplateCatalog(proxmox_vmid=9002, name="Active", category="vm", is_active=True))
    db_session.add(TemplateCatalog(proxmox_vmid=9003, name="Inactive", category="lxc", is_active=False))
    await db_session.commit()

    resp = await admin_client.get("/api/admin/templates/")
    assert resp.status_code == 200
    assert len(resp.json()) == 1  # only active by default

    resp2 = await admin_client.get("/api/admin/templates/?include_inactive=true")
    assert len(resp2.json()) == 2


@pytest.mark.asyncio
async def test_admin_update_template(admin_client: AsyncClient, db_session: AsyncSession):
    t = TemplateCatalog(proxmox_vmid=9004, name="Old Name", category="vm")
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    resp = await admin_client.patch(f"/api/admin/templates/{t.id}", json={"name": "New Name", "is_active": False})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_admin_delete_template(admin_client: AsyncClient, db_session: AsyncSession):
    t = TemplateCatalog(proxmox_vmid=9005, name="To Delete", category="vm")
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    resp = await admin_client.delete(f"/api/admin/templates/{t.id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_admin_proxmox_templates(admin_client: AsyncClient):
    resp = await admin_client.get("/api/admin/templates/proxmox-available")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_template_endpoints_require_admin(auth_client: AsyncClient):
    resp = await auth_client.post("/api/admin/templates/", json={"proxmox_vmid": 1, "name": "x", "category": "vm"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# User-facing Template Catalog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_list_templates(auth_client: AsyncClient, db_session: AsyncSession):
    db_session.add(TemplateCatalog(proxmox_vmid=9010, name="Available", category="vm", is_active=True))
    db_session.add(TemplateCatalog(proxmox_vmid=9011, name="Hidden", category="vm", is_active=False))
    await db_session.commit()

    resp = await auth_client.get("/api/templates/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Available"


@pytest.mark.asyncio
async def test_user_list_templates_filter_category(auth_client: AsyncClient, db_session: AsyncSession):
    db_session.add(TemplateCatalog(proxmox_vmid=9012, name="VM Template", category="vm", is_active=True))
    db_session.add(TemplateCatalog(proxmox_vmid=9013, name="LXC Template", category="lxc", is_active=True))
    await db_session.commit()

    resp = await auth_client.get("/api/templates/?category=lxc")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["category"] == "lxc"


# ---------------------------------------------------------------------------
# User Quota Requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_quota_request(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/quota-requests/",
        json={"request_type": "max_vms", "requested_value": 20, "reason": "Need more VMs"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["current_value"] == 5  # default quota
    assert data["requested_value"] == 20


@pytest.mark.asyncio
async def test_submit_duplicate_pending_request(auth_client: AsyncClient, db_session: AsyncSession, test_user: User):
    db_session.add(
        QuotaRequest(
            user_id=test_user.id,
            request_type="max_vms",
            current_value=5,
            requested_value=10,
            reason="First request",
        )
    )
    await db_session.commit()

    resp = await auth_client.post(
        "/api/quota-requests/",
        json={"request_type": "max_vms", "requested_value": 20, "reason": "Second request"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_submit_invalid_quota_type(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/quota-requests/",
        json={"request_type": "invalid_field", "requested_value": 20, "reason": "Bad type"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_submit_lower_value_rejected(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/quota-requests/",
        json={"request_type": "max_vms", "requested_value": 3, "reason": "Lower than current"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_my_quota_requests(auth_client: AsyncClient, db_session: AsyncSession, test_user: User):
    db_session.add(
        QuotaRequest(
            user_id=test_user.id, request_type="max_vcpus", current_value=16, requested_value=32, reason="ML work"
        )
    )
    await db_session.commit()

    resp = await auth_client.get("/api/quota-requests/")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert len(resp.json()["items"]) == 1


# ---------------------------------------------------------------------------
# Admin Quota Request Management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_list_quota_requests(admin_client: AsyncClient, db_session: AsyncSession, test_user: User):
    db_session.add(
        QuotaRequest(
            user_id=test_user.id, request_type="max_vms", current_value=5, requested_value=20, reason="Test"
        )
    )
    await db_session.commit()

    resp = await admin_client.get("/api/admin/quota-requests/")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


@pytest.mark.asyncio
async def test_admin_pending_count(admin_client: AsyncClient, db_session: AsyncSession, test_user: User):
    db_session.add(
        QuotaRequest(
            user_id=test_user.id, request_type="max_vms", current_value=5, requested_value=10, reason="Test"
        )
    )
    await db_session.commit()

    resp = await admin_client.get("/api/admin/quota-requests/pending/count")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


@pytest.mark.asyncio
async def test_admin_approve_quota_request(admin_client: AsyncClient, db_session: AsyncSession, test_user: User):
    qr = QuotaRequest(
        user_id=test_user.id, request_type="max_vms", current_value=5, requested_value=15, reason="Need more"
    )
    db_session.add(qr)
    await db_session.commit()
    await db_session.refresh(qr)

    resp = await admin_client.patch(
        f"/api/admin/quota-requests/{qr.id}",
        json={"status": "approved", "admin_notes": "Approved."},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    # Verify quota was auto-updated
    quota_resp = await admin_client.get(f"/api/admin/users/{test_user.id}/quota")
    assert quota_resp.json()["max_vms"] == 15


@pytest.mark.asyncio
async def test_admin_deny_quota_request(admin_client: AsyncClient, db_session: AsyncSession, test_user: User):
    qr = QuotaRequest(
        user_id=test_user.id, request_type="max_vcpus", current_value=16, requested_value=64, reason="Denied test"
    )
    db_session.add(qr)
    await db_session.commit()
    await db_session.refresh(qr)

    resp = await admin_client.patch(
        f"/api/admin/quota-requests/{qr.id}",
        json={"status": "denied", "admin_notes": "Too high."},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "denied"


@pytest.mark.asyncio
async def test_admin_cannot_re_review(admin_client: AsyncClient, db_session: AsyncSession, test_user: User):
    qr = QuotaRequest(
        user_id=test_user.id,
        request_type="max_disk_gb",
        current_value=500,
        requested_value=1000,
        reason="Storage",
        status="approved",
    )
    db_session.add(qr)
    await db_session.commit()
    await db_session.refresh(qr)

    resp = await admin_client.patch(
        f"/api/admin/quota-requests/{qr.id}", json={"status": "denied"}
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Admin System Settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_list_settings(admin_client: AsyncClient, db_session: AsyncSession):
    db_session.add(SystemSetting(key="test_setting", value="42", description="Test"))
    await db_session.commit()

    resp = await admin_client.get("/api/admin/settings/")
    assert resp.status_code == 200
    keys = [s["key"] for s in resp.json()]
    assert "test_setting" in keys


@pytest.mark.asyncio
async def test_admin_get_setting(admin_client: AsyncClient, db_session: AsyncSession):
    db_session.add(SystemSetting(key="motd", value="Hello!", description="MOTD"))
    await db_session.commit()

    resp = await admin_client.get("/api/admin/settings/motd")
    assert resp.status_code == 200
    assert resp.json()["value"] == "Hello!"


@pytest.mark.asyncio
async def test_admin_update_setting(admin_client: AsyncClient, db_session: AsyncSession):
    db_session.add(SystemSetting(key="overcommit_cpu_ratio", value="4.0", description="CPU OC"))
    await db_session.commit()

    resp = await admin_client.patch("/api/admin/settings/overcommit_cpu_ratio", json={"value": "2.0"})
    assert resp.status_code == 200
    assert resp.json()["value"] == "2.0"


@pytest.mark.asyncio
async def test_admin_setting_not_found(admin_client: AsyncClient):
    resp = await admin_client.get("/api/admin/settings/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_settings_require_admin(auth_client: AsyncClient):
    resp = await auth_client.get("/api/admin/settings/")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin Audit Logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_list_audit_logs(admin_client: AsyncClient, db_session: AsyncSession, test_user: User):
    db_session.add(
        AuditLog(user_id=test_user.id, action="create_vm", resource_type="vm", details='{"vmid": 100}')
    )
    await db_session.commit()

    resp = await admin_client.get("/api/admin/audit-logs/")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


@pytest.mark.asyncio
async def test_admin_audit_logs_filter_action(admin_client: AsyncClient, db_session: AsyncSession, test_user: User):
    db_session.add(AuditLog(user_id=test_user.id, action="create_vm", resource_type="vm"))
    db_session.add(AuditLog(user_id=test_user.id, action="delete_vm", resource_type="vm"))
    await db_session.commit()

    resp = await admin_client.get("/api/admin/audit-logs/?action=create_vm")
    assert resp.status_code == 200
    assert all(log["action"] == "create_vm" for log in resp.json()["items"])


@pytest.mark.asyncio
async def test_audit_logs_require_admin(auth_client: AsyncClient):
    resp = await auth_client.get("/api/admin/audit-logs/")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin User Detail Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_get_user_detail(admin_client: AsyncClient, test_user: User):
    resp = await admin_client.get(f"/api/admin/users/{test_user.id}")
    assert resp.status_code == 200
    assert resp.json()["username"] == "testuser"


@pytest.mark.asyncio
async def test_admin_get_user_resources(admin_client: AsyncClient, test_user: User):
    resp = await admin_client.get(f"/api/admin/users/{test_user.id}/resources")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_admin_delete_user(admin_client: AsyncClient, db_session: AsyncSession):
    from app.core.security import hash_password

    user = User(
        email="deleteme@test.com",
        username="deleteme",
        hashed_password=hash_password("password"),
        role="member",
        is_active=True,
        auth_provider="local",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    resp = await admin_client.delete(f"/api/admin/users/{user.id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_admin_cannot_delete_self(admin_client: AsyncClient, test_admin: User):
    resp = await admin_client.delete(f"/api/admin/users/{test_admin.id}")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Enhanced Admin Dashboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_dashboard_has_pending_quota_count(
    admin_client: AsyncClient, db_session: AsyncSession, test_user: User
):
    db_session.add(
        QuotaRequest(
            user_id=test_user.id, request_type="max_vms", current_value=5, requested_value=10, reason="Test"
        )
    )
    await db_session.commit()

    resp = await admin_client.get("/api/dashboard/admin/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "pending_quota_requests" in data
    assert data["pending_quota_requests"] >= 1
    assert "active_users" in data

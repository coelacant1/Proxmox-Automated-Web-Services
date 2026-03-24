"""Tests for API standardization: pagination, response envelopes, response models."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AuditLog, User


@pytest.mark.asyncio
async def test_paginated_response_structure(admin_client: AsyncClient, test_user: User, test_admin: User):
    """All paginated endpoints return items/total/page/per_page/pages."""
    resp = await admin_client.get("/api/admin/users/")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "per_page" in data
    assert "pages" in data
    assert data["page"] == 1
    assert data["per_page"] == 50
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_pagination_page_parameter(admin_client: AsyncClient, test_user: User, test_admin: User):
    """page=2 returns empty when there aren't enough items."""
    resp = await admin_client.get("/api/admin/users/?page=2&per_page=50")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 2
    assert len(data["items"]) == 0
    assert data["total"] >= 2


@pytest.mark.asyncio
async def test_pagination_per_page(admin_client: AsyncClient, test_user: User, test_admin: User):
    """per_page=1 returns exactly 1 item."""
    resp = await admin_client.get("/api/admin/users/?per_page=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] >= 2
    assert data["pages"] >= 2


@pytest.mark.asyncio
async def test_resources_paginated(auth_client: AsyncClient):
    """User resources endpoint uses pagination."""
    resp = await auth_client.get("/api/resources/")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_audit_logs_paginated_with_filter(admin_client: AsyncClient, db_session: AsyncSession, test_user: User):
    """Audit logs support pagination + filtering together."""
    for i in range(3):
        db_session.add(AuditLog(user_id=test_user.id, action="test_action", resource_type="vm"))
    db_session.add(AuditLog(user_id=test_user.id, action="other_action", resource_type="network"))
    await db_session.commit()

    resp = await admin_client.get("/api/admin/audit-logs/?action=test_action&per_page=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["pages"] == 2


@pytest.mark.asyncio
async def test_usage_response_model(auth_client: AsyncClient):
    """Usage endpoint returns proper typed response."""
    resp = await auth_client.get("/api/resources/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert "vms" in data
    assert "containers" in data
    assert "networks" in data
    assert "storage_buckets" in data
    assert all(isinstance(v, int) for v in data.values())


@pytest.mark.asyncio
async def test_security_headers_present(auth_client: AsyncClient):
    """All responses include security headers."""
    resp = await auth_client.get("/api/resources/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

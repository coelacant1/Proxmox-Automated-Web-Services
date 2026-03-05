"""Tests for cluster status endpoint and new Phase 9 models."""

import json
from datetime import UTC

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import QuotaRequest, SystemSetting, TemplateCatalog, User

# ---------------------------------------------------------------------------
# Cluster status endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cluster_status_authenticated(auth_client: AsyncClient):
    resp = await auth_client.get("/api/cluster/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_reachable"] is True
    assert data["node_count"] == 2
    assert data["nodes_online"] == 2
    # Must NOT contain raw capacity numbers
    for node in data["nodes"]:
        assert "mem" not in node
        assert "maxmem" not in node
        assert "disk" not in node
        assert "maxdisk" not in node
        assert "cpu" not in node
        assert "maxcpu" not in node


@pytest.mark.asyncio
async def test_cluster_status_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/cluster/status")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# TemplateCatalog model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_template_catalog_create(db_session: AsyncSession):
    template = TemplateCatalog(
        proxmox_vmid=9000,
        name="Ubuntu 22.04 LTS",
        description="Standard Ubuntu server template",
        os_type="linux",
        category="vm",
        min_cpu=1,
        min_ram_mb=1024,
        min_disk_gb=20,
        tags=json.dumps(["linux", "ubuntu", "lts"]),
    )
    db_session.add(template)
    await db_session.commit()
    await db_session.refresh(template)

    assert template.id is not None
    assert template.proxmox_vmid == 9000
    assert template.is_active is True
    assert json.loads(template.tags) == ["linux", "ubuntu", "lts"]


@pytest.mark.asyncio
async def test_template_catalog_unique_vmid(db_session: AsyncSession):
    t1 = TemplateCatalog(proxmox_vmid=9001, name="Template A", category="vm")
    db_session.add(t1)
    await db_session.commit()

    t2 = TemplateCatalog(proxmox_vmid=9001, name="Template B", category="vm")
    db_session.add(t2)
    with pytest.raises(Exception):  # IntegrityError
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# QuotaRequest model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quota_request_create(db_session: AsyncSession, test_user: User):
    qr = QuotaRequest(
        user_id=test_user.id,
        request_type="max_vms",
        current_value=5,
        requested_value=20,
        reason="Need more VMs for a project",
    )
    db_session.add(qr)
    await db_session.commit()
    await db_session.refresh(qr)

    assert qr.id is not None
    assert qr.status == "pending"
    assert qr.reviewed_by is None
    assert qr.reviewed_at is None


@pytest.mark.asyncio
async def test_quota_request_review(db_session: AsyncSession, test_user: User, test_admin: User):
    from datetime import datetime

    qr = QuotaRequest(
        user_id=test_user.id,
        request_type="max_vcpus",
        current_value=16,
        requested_value=32,
        reason="Running ML workloads",
    )
    db_session.add(qr)
    await db_session.commit()
    await db_session.refresh(qr)

    qr.status = "approved"
    qr.reviewed_by = test_admin.id
    qr.admin_notes = "Approved for ML usage"
    qr.reviewed_at = datetime.now(UTC)
    await db_session.commit()
    await db_session.refresh(qr)

    assert qr.status == "approved"
    assert qr.reviewed_by == test_admin.id


# ---------------------------------------------------------------------------
# SystemSetting model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_setting_create(db_session: AsyncSession):
    setting = SystemSetting(
        key="overcommit_cpu_ratio",
        value="4.0",
        description="CPU overcommit ratio",
    )
    db_session.add(setting)
    await db_session.commit()
    await db_session.refresh(setting)

    assert setting.key == "overcommit_cpu_ratio"
    assert setting.value == "4.0"


@pytest.mark.asyncio
async def test_system_setting_unique_key(db_session: AsyncSession):
    s1 = SystemSetting(key="test_key", value="a")
    db_session.add(s1)
    await db_session.commit()

    s2 = SystemSetting(key="test_key", value="b")
    db_session.add(s2)
    with pytest.raises(Exception):
        await db_session.commit()
    await db_session.rollback()

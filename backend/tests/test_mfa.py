"""Tests for MFA (TOTP) endpoints."""

import pyotp
import pytest
from httpx import AsyncClient

from app.models.models import User


@pytest.mark.asyncio
async def test_mfa_status_initially_disabled(auth_client: AsyncClient):
    r = await auth_client.get("/api/mfa/status")
    assert r.status_code == 200
    assert r.json()["is_enabled"] is False
    assert r.json()["has_totp"] is False


@pytest.mark.asyncio
async def test_mfa_setup_returns_secret_and_qr(auth_client: AsyncClient):
    r = await auth_client.post("/api/mfa/setup")
    assert r.status_code == 200
    data = r.json()
    assert "secret" in data
    assert "qr_code_base64" in data
    assert "provisioning_uri" in data
    assert len(data["backup_codes"]) == 10


@pytest.mark.asyncio
async def test_mfa_verify_activates(auth_client: AsyncClient):
    setup = await auth_client.post("/api/mfa/setup")
    secret = setup.json()["secret"]

    totp = pyotp.TOTP(secret)
    code = totp.now()

    r = await auth_client.post("/api/mfa/verify", json={"code": code})
    assert r.status_code == 200
    assert r.json()["message"] == "MFA enabled successfully"

    status = await auth_client.get("/api/mfa/status")
    assert status.json()["is_enabled"] is True


@pytest.mark.asyncio
async def test_mfa_verify_rejects_bad_code(auth_client: AsyncClient):
    await auth_client.post("/api/mfa/setup")

    r = await auth_client.post("/api/mfa/verify", json={"code": "000000"})
    assert r.status_code == 400
    assert "Invalid TOTP code" in r.json()["detail"]


@pytest.mark.asyncio
async def test_mfa_disable_with_totp(auth_client: AsyncClient):
    setup = await auth_client.post("/api/mfa/setup")
    secret = setup.json()["secret"]

    totp = pyotp.TOTP(secret)
    await auth_client.post("/api/mfa/verify", json={"code": totp.now()})

    r = await auth_client.post("/api/mfa/disable", json={"code": totp.now()})
    assert r.status_code == 200
    assert r.json()["message"] == "MFA disabled successfully"

    status = await auth_client.get("/api/mfa/status")
    assert status.json()["is_enabled"] is False


@pytest.mark.asyncio
async def test_mfa_disable_with_backup_code(auth_client: AsyncClient):
    setup = await auth_client.post("/api/mfa/setup")
    secret = setup.json()["secret"]
    backup_codes = setup.json()["backup_codes"]

    totp = pyotp.TOTP(secret)
    await auth_client.post("/api/mfa/verify", json={"code": totp.now()})

    r = await auth_client.post("/api/mfa/disable", json={"code": backup_codes[0]})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_login_requires_mfa_when_enabled(client: AsyncClient, test_user: User):
    """When MFA is enabled, login without code returns 403; with code returns 200."""
    from tests.conftest import make_token

    # First enable MFA via authenticated requests
    token = make_token(test_user)
    headers = {"Authorization": f"Bearer {token}"}

    setup = await client.post("/api/mfa/setup", headers=headers)
    secret = setup.json()["secret"]
    totp = pyotp.TOTP(secret)
    await client.post("/api/mfa/verify", headers=headers, json={"code": totp.now()})

    # Login without MFA code
    r = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpassword"},
    )
    assert r.status_code == 403
    assert "MFA code required" in r.json()["detail"]

    # Login with MFA code
    r = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpassword", "mfa_code": totp.now()},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()


@pytest.mark.asyncio
async def test_regenerate_backup_codes(auth_client: AsyncClient):
    setup = await auth_client.post("/api/mfa/setup")
    secret = setup.json()["secret"]
    old_codes = setup.json()["backup_codes"]

    totp = pyotp.TOTP(secret)
    await auth_client.post("/api/mfa/verify", json={"code": totp.now()})

    r = await auth_client.post(
        "/api/mfa/regenerate-backup-codes",
        json={"code": totp.now()},
    )
    assert r.status_code == 200
    new_codes = r.json()["backup_codes"]
    assert len(new_codes) == 10
    assert new_codes != old_codes

"""Auth router tests."""

import pytest

from app.core.security import create_access_token, decode_token, hash_password, validate_password, verify_password

# A password that satisfies default policy (8+ chars, upper, lower, digit)
VALID_PASSWORD = "Secure1Pass!x"


# --- Unit tests (no DB / no app) ---


def test_password_hashing():
    hashed = hash_password("testpassword")
    assert verify_password("testpassword", hashed)
    assert not verify_password("wrongpassword", hashed)


def test_create_and_decode_access_token():
    data = {"sub": "test-user-id"}
    token = create_access_token(data)
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "test-user-id"
    assert payload["type"] == "access"


def test_decode_invalid_token():
    payload = decode_token("invalid-token")
    assert payload is None


def test_validate_password_too_short():
    assert validate_password("Ab1") is not None


def test_validate_password_no_uppercase():
    assert validate_password("lowercase1") is not None


def test_validate_password_no_lowercase():
    assert validate_password("UPPERCASE1") is not None


def test_validate_password_no_digit():
    assert validate_password("NoDigitHere") is not None


def test_validate_password_valid():
    assert validate_password(VALID_PASSWORD) is None


# --- Integration tests (with mocked DB) ---


@pytest.mark.anyio
async def test_register_and_login(client):
    # Register
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "new@example.com",
            "username": "newuser",
            "password": VALID_PASSWORD,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "new@example.com"
    assert data["username"] == "newuser"
    assert data["role"] == "member"

    # Login
    resp = await client.post(
        "/api/auth/login",
        json={
            "username": "newuser",
            "password": VALID_PASSWORD,
        },
    )
    assert resp.status_code == 200
    tokens = resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"


@pytest.mark.anyio
async def test_register_weak_password(client):
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "weak@example.com",
            "username": "weakuser",
            "password": "short",
        },
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_register_duplicate_email(client):
    await client.post(
        "/api/auth/register",
        json={
            "email": "dup@example.com",
            "username": "user1",
            "password": VALID_PASSWORD,
        },
    )
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "dup@example.com",
            "username": "user2",
            "password": VALID_PASSWORD,
        },
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_register_duplicate_username(client):
    await client.post(
        "/api/auth/register",
        json={
            "email": "a@example.com",
            "username": "dupname",
            "password": VALID_PASSWORD,
        },
    )
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "b@example.com",
            "username": "dupname",
            "password": VALID_PASSWORD,
        },
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_login_wrong_password(client):
    await client.post(
        "/api/auth/register",
        json={
            "email": "wp@example.com",
            "username": "wpuser",
            "password": VALID_PASSWORD,
        },
    )
    resp = await client.post(
        "/api/auth/login",
        json={
            "username": "wpuser",
            "password": "WrongPass1",
        },
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_me_authenticated(auth_client, test_user):
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == test_user.email


@pytest.mark.anyio
async def test_me_unauthenticated(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_register_disabled_when_local_auth_off(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.local_auth_enabled", False)
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "no@example.com",
            "username": "nope",
            "password": VALID_PASSWORD,
        },
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_refresh_token_flow(client):
    # Register + login
    await client.post(
        "/api/auth/register",
        json={
            "email": "ref@example.com",
            "username": "refuser",
            "password": VALID_PASSWORD,
        },
    )
    login = await client.post(
        "/api/auth/login",
        json={
            "username": "refuser",
            "password": VALID_PASSWORD,
        },
    )
    refresh = login.json()["refresh_token"]

    # Refresh
    resp = await client.post("/api/auth/refresh", params={"refresh_token": refresh})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.anyio
async def test_refresh_with_invalid_token(client):
    resp = await client.post("/api/auth/refresh", params={"refresh_token": "garbage"})
    assert resp.status_code == 401

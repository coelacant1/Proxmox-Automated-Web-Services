"""Storage bucket API tests - upgraded with StorageBucket model."""

import pytest
from sqlalchemy import select

from app.models.models import StorageBucket


@pytest.mark.anyio
async def test_list_buckets_empty(auth_client):
    resp = await auth_client.get("/api/storage/buckets")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_create_bucket(auth_client, db_session):
    resp = await auth_client.post(
        "/api/storage/buckets",
        json={"name": "my-test-bucket"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "my-test-bucket"
    assert data["status"] == "created"

    result = await db_session.execute(select(StorageBucket).where(StorageBucket.name == "my-test-bucket"))
    assert result.scalar_one() is not None


@pytest.mark.anyio
async def test_create_bucket_unauthenticated(client):
    resp = await client.post("/api/storage/buckets", json={"name": "nope-bucket"})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_create_bucket_invalid_name(auth_client):
    resp = await auth_client.post("/api/storage/buckets", json={"name": "INVALID_NAME!"})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_bucket_duplicate(auth_client):
    await auth_client.post("/api/storage/buckets", json={"name": "dupe-bucket"})
    resp = await auth_client.post("/api/storage/buckets", json={"name": "dupe-bucket"})
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_get_bucket(auth_client):
    create = await auth_client.post("/api/storage/buckets", json={"name": "detail-bucket"})
    bucket_id = create.json()["id"]

    resp = await auth_client.get(f"/api/storage/buckets/{bucket_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "detail-bucket"
    assert "versioning_enabled" in resp.json()


@pytest.mark.anyio
async def test_update_bucket(auth_client):
    create = await auth_client.post("/api/storage/buckets", json={"name": "update-bucket"})
    bucket_id = create.json()["id"]

    resp = await auth_client.patch(
        f"/api/storage/buckets/{bucket_id}",
        json={"versioning_enabled": True, "tags": {"env": "test"}},
    )
    assert resp.status_code == 200

    detail = await auth_client.get(f"/api/storage/buckets/{bucket_id}")
    assert detail.json()["versioning_enabled"] is True
    assert detail.json()["tags"]["env"] == "test"


@pytest.mark.anyio
async def test_list_buckets_after_create(auth_client):
    await auth_client.post("/api/storage/buckets", json={"name": "bucket-one"})
    await auth_client.post("/api/storage/buckets", json={"name": "bucket-two"})
    resp = await auth_client.get("/api/storage/buckets")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.anyio
async def test_delete_bucket(auth_client):
    create = await auth_client.post("/api/storage/buckets", json={"name": "delete-bucket"})
    bucket_id = create.json()["id"]

    resp = await auth_client.delete(f"/api/storage/buckets/{bucket_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    resp = await auth_client.get(f"/api/storage/buckets/{bucket_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_bucket_quota_exceeded(auth_client):
    """Default quota is 5 buckets."""
    for i in range(5):
        resp = await auth_client.post("/api/storage/buckets", json={"name": f"quota-bucket-{i}"})
        assert resp.status_code == 201

    resp = await auth_client.post("/api/storage/buckets", json={"name": "quota-overflow"})
    assert resp.status_code == 403
    assert "quota" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_list_objects(auth_client):
    create = await auth_client.post("/api/storage/buckets", json={"name": "objects-bucket"})
    bucket_id = create.json()["id"]

    resp = await auth_client.get(f"/api/storage/buckets/{bucket_id}/objects")
    assert resp.status_code == 200
    assert "objects" in resp.json()

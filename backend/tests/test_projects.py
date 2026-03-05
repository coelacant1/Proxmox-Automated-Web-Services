"""Tests for Project CRUD API."""

import pytest


@pytest.mark.anyio
async def test_create_project(auth_client):
    resp = await auth_client.post("/api/projects/", json={"name": "Test Project", "description": "A test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Project"
    assert data["slug"] == "test-project"
    assert data["is_personal"] is False


@pytest.mark.anyio
async def test_list_projects(auth_client):
    # User should have a personal project from registration + any created
    await auth_client.post("/api/projects/", json={"name": "Listed Project"})
    resp = await auth_client.get("/api/projects/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    names = [p["name"] for p in data["items"]]
    assert "Listed Project" in names


@pytest.mark.anyio
async def test_get_project(auth_client):
    resp = await auth_client.post("/api/projects/", json={"name": "Get Me"})
    project_id = resp.json()["id"]
    resp = await auth_client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Get Me"


@pytest.mark.anyio
async def test_update_project(auth_client):
    resp = await auth_client.post("/api/projects/", json={"name": "Old Name"})
    project_id = resp.json()["id"]
    resp = await auth_client.patch(f"/api/projects/{project_id}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


@pytest.mark.anyio
async def test_delete_project(auth_client):
    resp = await auth_client.post("/api/projects/", json={"name": "Delete Me"})
    project_id = resp.json()["id"]
    resp = await auth_client.delete(f"/api/projects/{project_id}")
    assert resp.status_code == 204
    resp = await auth_client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_cannot_delete_personal_project(auth_client):
    # Create a personal project via registration (happens automatically)
    resp = await auth_client.get("/api/projects/")
    personal = [p for p in resp.json()["items"] if p["is_personal"]]
    if personal:
        resp = await auth_client.delete(f"/api/projects/{personal[0]['id']}")
        assert resp.status_code == 400


@pytest.mark.anyio
async def test_list_project_members(auth_client):
    resp = await auth_client.post("/api/projects/", json={"name": "Members Test"})
    project_id = resp.json()["id"]
    resp = await auth_client.get(f"/api/projects/{project_id}/members")
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) >= 1
    assert members[0]["role"] == "owner"


@pytest.mark.anyio
async def test_duplicate_slug_gets_suffix(auth_client):
    await auth_client.post("/api/projects/", json={"name": "Same Name"})
    resp = await auth_client.post("/api/projects/", json={"name": "Same Name"})
    assert resp.status_code == 201
    assert resp.json()["slug"].startswith("same-name")
    assert resp.json()["slug"] != "same-name"

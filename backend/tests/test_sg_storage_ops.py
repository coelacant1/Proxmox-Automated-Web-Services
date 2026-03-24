"""Tests for security group templates, attach/detach, and storage object operations."""

import uuid

import pytest

# --- Security Group Templates --------------------------------------------


@pytest.mark.anyio
async def test_list_sg_templates(auth_client):
    r = await auth_client.get("/api/security-groups/templates")
    assert r.status_code == 200
    data = r.json()
    assert "web-server" in data
    assert "ssh-only" in data
    assert "database" in data
    assert data["web-server"]["rule_count"] == 2


@pytest.mark.anyio
async def test_create_sg_from_template(auth_client):
    r = await auth_client.post("/api/security-groups/from-template/web-server")
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Web Server"
    assert len(data["rules"]) == 2


@pytest.mark.anyio
async def test_create_sg_from_invalid_template(auth_client):
    r = await auth_client.post("/api/security-groups/from-template/nonexistent")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_create_sg_from_template_duplicate(auth_client):
    await auth_client.post("/api/security-groups/from-template/ssh-only")
    r = await auth_client.post("/api/security-groups/from-template/ssh-only")
    assert r.status_code == 409


# --- Security Group Attach/Detach ----------------------------------------


@pytest.mark.anyio
async def test_attach_sg_to_vm(auth_client):
    # Create a VM
    vm = await auth_client.post("/api/compute/vms", json={"name": "sg-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    # Create a security group
    sg = await auth_client.post("/api/security-groups/", json={"name": "attach-test", "description": "test"})
    sg_id = sg.json()["id"]

    # Attach
    r = await auth_client.post(f"/api/security-groups/{sg_id}/attach", json={"resource_id": vm_id})
    assert r.status_code == 201
    assert r.json()["status"] == "attached"


@pytest.mark.anyio
async def test_attach_sg_duplicate(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "sg-dup-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    sg = await auth_client.post("/api/security-groups/", json={"name": "dup-test", "description": "test"})
    sg_id = sg.json()["id"]

    await auth_client.post(f"/api/security-groups/{sg_id}/attach", json={"resource_id": vm_id})
    r = await auth_client.post(f"/api/security-groups/{sg_id}/attach", json={"resource_id": vm_id})
    assert r.status_code == 409


@pytest.mark.anyio
async def test_detach_sg(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "sg-det-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    sg = await auth_client.post("/api/security-groups/", json={"name": "detach-test", "description": "test"})
    sg_id = sg.json()["id"]

    await auth_client.post(f"/api/security-groups/{sg_id}/attach", json={"resource_id": vm_id})
    r = await auth_client.post(f"/api/security-groups/{sg_id}/detach", json={"resource_id": vm_id})
    assert r.status_code == 200
    assert r.json()["status"] == "detached"


@pytest.mark.anyio
async def test_detach_sg_not_attached(auth_client):
    sg = await auth_client.post("/api/security-groups/", json={"name": "noattach-test", "description": "test"})
    sg_id = sg.json()["id"]

    r = await auth_client.post(
        f"/api/security-groups/{sg_id}/detach",
        json={"resource_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404


@pytest.mark.anyio
async def test_list_attached_resources(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "sg-list-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    sg = await auth_client.post("/api/security-groups/", json={"name": "list-res-test", "description": "test"})
    sg_id = sg.json()["id"]

    await auth_client.post(f"/api/security-groups/{sg_id}/attach", json={"resource_id": vm_id})
    r = await auth_client.get(f"/api/security-groups/{sg_id}/resources")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == vm_id


# --- Storage Object Operations ------------------------------------------


async def _create_bucket(auth_client, name="test-bucket-obj"):
    r = await auth_client.post("/api/storage/buckets", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


@pytest.mark.anyio
async def test_upload_object(auth_client):
    bucket_id = await _create_bucket(auth_client, "upload-test-bucket")
    r = await auth_client.put(
        f"/api/storage/buckets/{bucket_id}/objects/hello.txt",
        content=b"Hello world",
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 200
    assert r.json()["key"] == "hello.txt"
    assert r.json()["status"] == "uploaded"


@pytest.mark.anyio
async def test_download_object(auth_client):
    bucket_id = await _create_bucket(auth_client, "download-test-bucket")
    r = await auth_client.get(f"/api/storage/buckets/{bucket_id}/objects/somefile.txt")
    assert r.status_code == 200


@pytest.mark.anyio
async def test_delete_object(auth_client):
    bucket_id = await _create_bucket(auth_client, "delete-obj-bucket")
    r = await auth_client.delete(f"/api/storage/buckets/{bucket_id}/objects/old.txt")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"


@pytest.mark.anyio
async def test_presigned_url(auth_client):
    bucket_id = await _create_bucket(auth_client, "presign-test-bucket")
    r = await auth_client.post(
        f"/api/storage/buckets/{bucket_id}/presign",
        json={"key": "report.pdf", "expires_in": 7200, "method": "GET"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "url" in data
    assert data["method"] == "GET"
    assert data["expires_in"] == 7200


@pytest.mark.anyio
async def test_presigned_url_put(auth_client):
    bucket_id = await _create_bucket(auth_client, "presign-put-bucket")
    r = await auth_client.post(
        f"/api/storage/buckets/{bucket_id}/presign",
        json={"key": "upload.bin", "method": "PUT"},
    )
    assert r.status_code == 200
    assert r.json()["method"] == "PUT"


@pytest.mark.anyio
async def test_presigned_url_invalid_method(auth_client):
    bucket_id = await _create_bucket(auth_client, "presign-bad-bucket")
    r = await auth_client.post(
        f"/api/storage/buckets/{bucket_id}/presign",
        json={"key": "file.txt", "method": "DELETE"},
    )
    assert r.status_code == 422

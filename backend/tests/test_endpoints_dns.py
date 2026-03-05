"""Service endpoint and DNS API tests."""

import pytest


# --- Endpoints -----------------------------------------------------------


@pytest.mark.anyio
async def test_list_endpoints_empty(auth_client):
    resp = await auth_client.get("/api/endpoints")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_create_endpoint(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "ep-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    resp = await auth_client.post(
        "/api/endpoints",
        json={
            "resource_id": vm_id,
            "name": "Web Server",
            "protocol": "http",
            "internal_port": 8080,
            "subdomain": "my-app",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["subdomain"] == "my-app"
    assert data["fqdn"] == "my-app.paws.local"
    assert data["internal_port"] == 8080


@pytest.mark.anyio
async def test_create_endpoint_reserved_subdomain(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "reserved-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    resp = await auth_client.post(
        "/api/endpoints",
        json={"resource_id": vm_id, "name": "Bad", "internal_port": 80, "subdomain": "admin"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_endpoint_duplicate_subdomain(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "dupe-ep-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    await auth_client.post(
        "/api/endpoints",
        json={"resource_id": vm_id, "name": "First", "internal_port": 80, "subdomain": "unique-app"},
    )
    resp = await auth_client.post(
        "/api/endpoints",
        json={"resource_id": vm_id, "name": "Second", "internal_port": 80, "subdomain": "unique-app"},
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_endpoint_connection_info(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "info-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    ep = await auth_client.post(
        "/api/endpoints",
        json={"resource_id": vm_id, "name": "Info Svc", "internal_port": 3000, "subdomain": "info-svc"},
    )
    ep_id = ep.json()["id"]

    resp = await auth_client.get(f"/api/endpoints/{ep_id}/connection-info")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://info-svc.paws.local"


@pytest.mark.anyio
async def test_update_endpoint(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "upd-ep-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    ep = await auth_client.post(
        "/api/endpoints",
        json={"resource_id": vm_id, "name": "Old Name", "internal_port": 80, "subdomain": "updatable"},
    )
    ep_id = ep.json()["id"]

    resp = await auth_client.patch(f"/api/endpoints/{ep_id}", json={"name": "New Name", "is_active": False})
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_delete_endpoint(auth_client):
    vm = await auth_client.post("/api/compute/vms", json={"name": "del-ep-vm", "template_vmid": 9000})
    vm_id = vm.json()["id"]

    ep = await auth_client.post(
        "/api/endpoints",
        json={"resource_id": vm_id, "name": "Deletable", "internal_port": 80, "subdomain": "deletable"},
    )
    ep_id = ep.json()["id"]

    resp = await auth_client.delete(f"/api/endpoints/{ep_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


# --- DNS Records ---------------------------------------------------------


@pytest.mark.anyio
async def test_list_dns_empty(auth_client):
    resp = await auth_client.get("/api/dns")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_create_dns_record(auth_client):
    resp = await auth_client.post(
        "/api/dns",
        json={"record_type": "A", "name": "app.internal", "value": "10.0.0.5"},
    )
    assert resp.status_code == 201
    assert resp.json()["record_type"] == "A"
    assert resp.json()["name"] == "app.internal"


@pytest.mark.anyio
async def test_create_dns_invalid_type(auth_client):
    resp = await auth_client.post(
        "/api/dns",
        json={"record_type": "MX", "name": "bad.internal", "value": "10.0.0.1"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_dns_invalid_ttl(auth_client):
    resp = await auth_client.post(
        "/api/dns",
        json={"record_type": "A", "name": "ttl.internal", "value": "10.0.0.1", "ttl": 10},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_update_dns_record(auth_client):
    create = await auth_client.post(
        "/api/dns",
        json={"record_type": "A", "name": "upd.internal", "value": "10.0.0.5"},
    )
    record_id = create.json()["id"]

    resp = await auth_client.patch(f"/api/dns/{record_id}", json={"value": "10.0.0.6", "ttl": 600})
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_delete_dns_record(auth_client):
    create = await auth_client.post(
        "/api/dns",
        json={"record_type": "CNAME", "name": "del.internal", "value": "app.internal"},
    )
    record_id = create.json()["id"]

    resp = await auth_client.delete(f"/api/dns/{record_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.anyio
async def test_list_dns_filtered(auth_client):
    await auth_client.post("/api/dns", json={"record_type": "A", "name": "a.internal", "value": "10.0.0.1"})
    await auth_client.post("/api/dns", json={"record_type": "CNAME", "name": "c.internal", "value": "a.internal"})

    resp = await auth_client.get("/api/dns", params={"record_type": "A"})
    assert resp.status_code == 200
    assert all(r["record_type"] == "A" for r in resp.json())

"""Tests for security, event publisher, retention engine, static IPs, endpoint quotas, namespace provisioning."""

import pytest

from app.core.validators import (
    validate_cidr,
    validate_hostname,
    validate_port,
    validate_subdomain,
    validate_vmid,
    validate_webhook_url,
    sanitize_display_name,
)
from app.services.event_publisher import (
    configure_action,
    get_action_config,
    get_recent_events,
    publish_event,
)
from app.services.retention_engine import (
    evaluate_retention,
    get_user_retention,
    set_user_retention,
)


# --- Validators ----------------------------------------------------------


class TestValidators:
    def test_validate_hostname_valid(self):
        assert validate_hostname("my-host") == "my-host"

    def test_validate_hostname_invalid(self):
        with pytest.raises(ValueError):
            validate_hostname("-bad")

    def test_validate_hostname_too_long(self):
        with pytest.raises(ValueError):
            validate_hostname("a" * 64)

    def test_validate_subdomain(self):
        assert validate_subdomain("app.my-service") == "app.my-service"

    def test_validate_cidr(self):
        assert validate_cidr("10.0.0.0/16") == "10.0.0.0/16"

    def test_validate_cidr_invalid(self):
        with pytest.raises(ValueError):
            validate_cidr("not-a-cidr")

    def test_validate_port_valid(self):
        assert validate_port(8080) == 8080

    def test_validate_port_invalid(self):
        with pytest.raises(ValueError):
            validate_port(70000)

    def test_validate_vmid_valid(self):
        assert validate_vmid(100) == 100

    def test_validate_vmid_invalid(self):
        with pytest.raises(ValueError):
            validate_vmid(50)

    def test_validate_webhook_url_https(self):
        assert validate_webhook_url("https://example.com/hook") == "https://example.com/hook"

    def test_validate_webhook_url_no_http(self):
        with pytest.raises(ValueError):
            validate_webhook_url("http://example.com/hook")

    def test_validate_webhook_url_localhost_blocked(self):
        with pytest.raises(ValueError):
            validate_webhook_url("https://localhost/hook")

    def test_validate_webhook_url_private_ip_blocked(self):
        with pytest.raises(ValueError):
            validate_webhook_url("https://192.168.1.1/hook")

    def test_sanitize_display_name(self):
        assert sanitize_display_name("  My VM  ") == "My VM"

    def test_sanitize_display_name_too_long(self):
        with pytest.raises(ValueError):
            sanitize_display_name("a" * 200)

    def test_sanitize_display_name_empty(self):
        with pytest.raises(ValueError):
            sanitize_display_name("   ")


# --- Event Publisher -----------------------------------------------------


@pytest.mark.anyio
async def test_publish_vm_crashed():
    configure_action("vm.crashed.auto_restart", True)
    event = await publish_event("vm.crashed", resource_id="vm-123", user_id="user-1")
    assert "auto_restart" in event["actions_fired"]


@pytest.mark.anyio
async def test_publish_backup_failed():
    event = await publish_event("backup.failed", user_id="user-2")
    assert "notify" in event["actions_fired"]


@pytest.mark.anyio
async def test_publish_alarm_triggered():
    configure_action("alarm.triggered.webhook", True)
    event = await publish_event("alarm.triggered", resource_id="alarm-1")
    assert "notify" in event["actions_fired"]
    assert "webhook" in event["actions_fired"]


@pytest.mark.anyio
async def test_action_config():
    configure_action("vm.crashed.auto_restart", False)
    event = await publish_event("vm.crashed", resource_id="vm-off")
    assert "auto_restart" not in event["actions_fired"]
    configure_action("vm.crashed.auto_restart", True)


@pytest.mark.anyio
async def test_recent_events():
    await publish_event("test.event", resource_id="x")
    events = get_recent_events(event_type="test.event")
    assert len(events) >= 1


@pytest.mark.anyio
async def test_get_action_config():
    config = get_action_config()
    assert "backup.failed.notify" in config


# --- Retention Engine ----------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_retention_default():
    backups = [{"id": f"bk-{i}", "timestamp": 1700000000 + i * 3600} for i in range(10)]
    result = await evaluate_retention("user-ret", backups, dry_run=True)
    assert result["keeping"] == 3
    assert result["pruning"] == 7
    assert result["dry_run"] is True


@pytest.mark.anyio
async def test_user_retention_override():
    set_user_retention("user-custom", {"keep_last": 5})
    policy = get_user_retention("user-custom")
    assert policy["keep_last"] == 5

    backups = [{"id": f"bk-{i}", "timestamp": 1700000000 + i * 3600} for i in range(10)]
    result = await evaluate_retention("user-custom", backups)
    assert result["keeping"] == 5


# --- Static IPs ----------------------------------------------------------


@pytest.mark.anyio
async def test_reserve_static_ip(auth_client):
    r = await auth_client.post(
        "/api/networking/vpcs/test-vpc/ips",
        json={"subnet_cidr": "10.0.1.0/24", "ip_address": "10.0.1.50"},
    )
    assert r.status_code == 200
    assert r.json()["ip"] == "10.0.1.50"


@pytest.mark.anyio
async def test_reserve_static_ip_auto(auth_client):
    r = await auth_client.post(
        "/api/networking/vpcs/test-vpc-auto/ips",
        json={"subnet_cidr": "10.0.2.0/24"},
    )
    assert r.status_code == 200
    assert r.json()["ip"].startswith("10.0.2.")


@pytest.mark.anyio
async def test_list_static_ips(auth_client):
    await auth_client.post(
        "/api/networking/vpcs/test-vpc-list/ips",
        json={"subnet_cidr": "10.0.3.0/24", "ip_address": "10.0.3.10"},
    )
    r = await auth_client.get("/api/networking/vpcs/test-vpc-list/ips")
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.anyio
async def test_release_static_ip(auth_client):
    await auth_client.post(
        "/api/networking/vpcs/test-vpc-rel/ips",
        json={"subnet_cidr": "10.0.4.0/24", "ip_address": "10.0.4.20"},
    )
    r = await auth_client.delete("/api/networking/vpcs/test-vpc-rel/ips/10.0.4.20")
    assert r.status_code == 200
    assert r.json()["status"] == "released"


@pytest.mark.anyio
async def test_reserve_duplicate_ip(auth_client):
    await auth_client.post(
        "/api/networking/vpcs/test-vpc-dup/ips",
        json={"subnet_cidr": "10.0.5.0/24", "ip_address": "10.0.5.10"},
    )
    r = await auth_client.post(
        "/api/networking/vpcs/test-vpc-dup/ips",
        json={"subnet_cidr": "10.0.5.0/24", "ip_address": "10.0.5.10"},
    )
    assert r.status_code == 409


# --- Endpoint Quotas -----------------------------------------------------


@pytest.mark.anyio
async def test_endpoint_quota(auth_client):
    r = await auth_client.get("/api/endpoints/quota")
    assert r.status_code == 200
    assert "max_endpoints" in r.json()
    assert "remaining" in r.json()

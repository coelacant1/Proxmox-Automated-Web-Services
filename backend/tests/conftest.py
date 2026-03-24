"""Shared test fixtures for the PAWS backend test suite.

Provides:
- In-memory SQLite database with all tables auto-created per test
- Dependency overrides so API tests never hit real Postgres/Proxmox/S3/Redis
- Mock Proxmox client and storage service
- Authenticated test client helpers
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.models.models import User, UserQuota

# ---------------------------------------------------------------------------
# In-memory async SQLite engine (no Postgres needed)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(test_engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    """Enable foreign keys in SQLite."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# ---------------------------------------------------------------------------
# DB session fixture - creates tables fresh per test
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Mock external services
# ---------------------------------------------------------------------------


class _ChainableMock:
    """Proxmoxer-style chainable API mock.

    Any attribute/call chain returns self; .get()/.post()/.put()/.delete() return [].
    """

    def __getattr__(self, name: str):
        if name in ("get", "post", "put", "delete"):
            return lambda **kw: []
        return self

    def __call__(self, *args, **kwargs):
        return self


class MockProxmoxClient:
    """Fake ProxmoxClient that returns realistic data without network calls."""

    @property
    def api(self):
        """Chainable mock for raw proxmoxer API access (e.g. api.nodes(x).qemu(y).firewall.rules.get())."""
        return _ChainableMock()

    def get_nodes(self) -> list[dict[str, Any]]:
        return [
            {
                "node": "pve1",
                "status": "online",
                "cpu": 0.15,
                "maxcpu": 16,
                "mem": 8 * 1024**3,
                "maxmem": 64 * 1024**3,
                "disk": 100 * 1024**3,
                "maxdisk": 1000 * 1024**3,
                "uptime": 86400,
            },
            {
                "node": "pve2",
                "status": "online",
                "cpu": 0.45,
                "maxcpu": 16,
                "mem": 32 * 1024**3,
                "maxmem": 64 * 1024**3,
                "disk": 500 * 1024**3,
                "maxdisk": 1000 * 1024**3,
                "uptime": 86400,
            },
        ]

    def get_node_status(self, node: str) -> dict[str, Any]:
        return {"node": node, "status": "running", "cpu": 0.15, "uptime": 86400}

    def get_cluster_status(self) -> list[dict[str, Any]]:
        return [{"type": "cluster", "name": "paws-cluster", "nodes": 2, "quorate": 1}]

    def get_cluster_resources(self, resource_type: str | None = None) -> list[dict[str, Any]]:
        return []

    def clone_vm(self, node: str, source_vmid: int, new_vmid: int, **kw: Any) -> str:
        return f"UPID:{node}:00001234:00AB12CD:clonevm:{new_vmid}:user@pam:"

    def get_next_vmid(self) -> int:
        return 500

    def create_vm(self, node: str, vmid: int, **kw: Any) -> str:
        return f"UPID:{node}:00001234:00AB12CD:createvm:{vmid}:user@pam:"

    def get_vm_status(self, node: str, vmid: int) -> dict[str, Any]:
        return {"vmid": vmid, "status": "running", "cpu": 0.05, "mem": 512 * 1024**2}

    def get_vm_config(self, node: str, vmid: int) -> dict[str, Any]:
        return {"cores": 2, "memory": 2048, "name": f"vm-{vmid}"}

    def start_vm(self, node: str, vmid: int) -> str:
        return f"UPID:{node}:startvm:{vmid}"

    def stop_vm(self, node: str, vmid: int) -> str:
        return f"UPID:{node}:stopvm:{vmid}"

    def shutdown_vm(self, node: str, vmid: int) -> str:
        return f"UPID:{node}:shutdownvm:{vmid}"

    def reboot_vm(self, node: str, vmid: int) -> str:
        return f"UPID:{node}:rebootvm:{vmid}"

    def suspend_vm(self, node: str, vmid: int, to_disk: bool = False) -> str:
        return f"UPID:{node}:suspendvm:{vmid}"

    def resume_vm(self, node: str, vmid: int) -> str:
        return f"UPID:{node}:resumevm:{vmid}"

    def delete_vm(self, node: str, vmid: int) -> str:
        return f"UPID:{node}:destroyvm:{vmid}"

    def update_vm_config(self, node: str, vmid: int, **kw: Any) -> None:
        pass

    def resize_vm_disk(self, node: str, vmid: int, disk: str, size: str) -> None:
        pass

    def resize_vm(self, node: str, vmid: int, cores: int, memory_mb: int) -> None:
        pass

    def create_container(self, node: str, vmid: int, **kw: Any) -> str:
        return f"UPID:{node}:createct:{vmid}"

    def get_container_status(self, node: str, vmid: int) -> dict[str, Any]:
        return {"vmid": vmid, "status": "running"}

    def start_container(self, node: str, vmid: int) -> str:
        return f"UPID:{node}:startct:{vmid}"

    def stop_container(self, node: str, vmid: int) -> str:
        return f"UPID:{node}:stopct:{vmid}"

    def shutdown_container(self, node: str, vmid: int) -> str:
        return f"UPID:{node}:shutdownct:{vmid}"

    def delete_container(self, node: str, vmid: int) -> str:
        return f"UPID:{node}:destroyct:{vmid}"

    def get_storage_list(self, node: str | None = None) -> list[dict[str, Any]]:
        return [{"storage": "local-lvm", "type": "lvmthin", "content": "images,rootdir"}]

    def get_storage_content(self, node: str, storage: str) -> list[dict[str, Any]]:
        return []

    def get_vm_templates(self) -> list[dict[str, Any]]:
        return [{"vmid": 9000, "name": "ubuntu-22.04", "template": 1, "node": "pve1"}]

    def get_container_templates(self, node: str, storage: str) -> list[dict[str, Any]]:
        return []

    def create_snapshot(self, node: str, vmid: int, snapname: str, vmtype: str = "qemu", **kw: Any) -> str:
        return f"UPID:{node}:snapshot:{vmid}"

    def list_snapshots(self, node: str, vmid: int, vmtype: str = "qemu") -> list[dict[str, Any]]:
        return [{"name": "current", "description": "", "snaptime": 0}]

    def delete_snapshot(self, node: str, vmid: int, snapname: str, vmtype: str = "qemu") -> str:
        return f"UPID:{node}:delsnap:{vmid}"

    def rollback_snapshot(self, node: str, vmid: int, snapname: str, vmtype: str = "qemu") -> str:
        return f"UPID:{node}:rollback:{vmid}"

    def get_task_status(self, node: str, upid: str) -> dict[str, Any]:
        return {"status": "OK", "exitstatus": "OK"}

    def get_node_tasks(self, node: str, vmid: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [{"upid": "UPID:node1:task:100", "type": "qmstart", "status": "OK", "starttime": 1700000000}]

    def get_rrd_data(self, node: str, vmid: int, vmtype: str = "qemu", timeframe: str = "hour") -> list[dict[str, Any]]:
        return [{"time": 1700000000, "cpu": 0.15, "mem": 512000000, "netin": 1024, "netout": 2048}]

    def get_sdn_zones(self) -> list[dict[str, Any]]:
        return [{"zone": "paws", "type": "evpn"}]

    def get_sdn_vnets(self) -> list[dict[str, Any]]:
        return [{"vnet": "testvn1", "zone": "paws", "alias": "test-net"}]

    def get_sdn_vnet(self, vnet: str) -> dict[str, Any]:
        return {"vnet": vnet, "zone": "paws"}

    def get_sdn_subnets(self, vnet: str) -> list[dict[str, Any]]:
        return []

    def create_sdn_vnet(self, vnet: str, zone: str, **kw: Any) -> None:
        pass

    def create_sdn_subnet(self, vnet: str, subnet: str, gateway: str, **kw: Any) -> None:
        pass

    def delete_sdn_vnet(self, vnet: str) -> None:
        pass

    def delete_sdn_subnet(self, vnet: str, subnet_id: str) -> None:
        pass

    def apply_sdn(self) -> None:
        pass

    def get_firewall_rules(self, node: str, vmid: int, vmtype: str = "qemu") -> list[dict[str, Any]]:
        return []

    def create_firewall_rule(self, node: str, vmid: int, vmtype: str = "qemu", **kw: Any) -> None:
        pass

    def delete_firewall_rule(self, node: str, vmid: int, vmtype: str = "qemu", pos: int = 0) -> None:
        pass

    def set_firewall_options(self, node: str, vmid: int, vmtype: str = "qemu", **kw: Any) -> None:
        pass

    def clear_firewall_rules_by_comment(
        self,
        node: str,
        vmid: int,
        vmtype: str = "qemu",
        comment_prefix: str = "",
    ) -> int:
        return 0

    def get_vnc_ticket(self, node: str, vmid: int, vmtype: str = "qemu") -> dict[str, Any]:
        return {"ticket": "PVEVNC:abc123", "port": 5900}

    def get_terminal_proxy(self, node: str, vmid: int, vmtype: str = "qemu") -> dict[str, Any]:
        return {"ticket": "PVETERM:abc123", "port": 5901}

    def get_spice_ticket(self, node: str, vmid: int, vmtype: str = "qemu") -> dict[str, Any]:
        return {"ticket": "PVESPICE:abc123", "proxy": "node1.example.com"}

    def create_backup(self, node: str, vmid: int, **kwargs: Any) -> str:
        return "UPID:node1:00001234:00000001:00000000:vzdump::root@pam:"

    def convert_to_template(self, node: str, vmid: int) -> None:
        pass

    def get_agent_info(self, node: str, vmid: int) -> dict[str, Any]:
        return {"version": "5.2.0", "supported_commands": ["guest-info", "guest-exec"]}

    def find_vm_node(self, vmid: int) -> str | None:
        return "pve1"

    def get_resource_type(self, vmid: int) -> str | None:
        return "qemu"

    def get_container_disk_storage(self, node: str, vmid: int) -> str:
        return "local-lvm"

    def get_vm_disk_storage(self, node: str, vmid: int) -> str:
        return "local-lvm"

    def is_storage_shared(self, storage: str) -> bool:
        return True

    def clone_container(self, node: str, source_vmid: int, new_vmid: int, **kw: Any) -> str:
        return f"UPID:{node}:00001234:00AB12CD:clonect:{new_vmid}:user@pam:"

    def wait_for_task(self, node: str, upid: str, timeout: int = 300) -> dict[str, Any]:
        return {"status": "OK", "exitstatus": "OK"}

    def set_container_config(self, node: str, vmid: int, **kw: Any) -> None:
        pass

    def regenerate_cloudinit(self, node: str, vmid: int) -> None:
        pass

    def get_agent_network_interfaces(self, node: str, vmid: int) -> list[dict[str, Any]]:
        return []

    def migrate_vm(self, node: str, vmid: int, target: str, online: bool = False) -> str:
        return f"UPID:{node}:migratevm:{vmid}"

    def migrate_container(self, node: str, vmid: int, target: str, online: bool = False) -> str:
        return f"UPID:{node}:migratect:{vmid}"

    def get_session_ticket(self) -> tuple[str, str]:
        return ("user@pam", "PVE:ticket:mock")

    def get_container_config(self, node: str, vmid: int) -> dict[str, Any]:
        return {"cores": 1, "memory": 512, "hostname": f"ct-{vmid}"}

    def create_pool(self, pool_name: str) -> None:
        pass

    def pool_exists(self, pool_name: str) -> bool:
        return True

    def add_to_pool(self, pool_name: str, vmid: int) -> None:
        pass

    def remove_from_pool(self, pool_name: str, vmid: int) -> None:
        pass

    def delete_pool(self, pool_name: str) -> None:
        pass

    def get_pool_name_for_user(self, username: str) -> str:
        return f"paws-{username}"

    def update_container_config(self, node: str, vmid: int, **kw: Any) -> None:
        pass

    def delete_volume(self, node: str, storage: str, volume: str) -> None:
        pass

    def delete_storage_content(self, node: str, storage: str, volume: str) -> None:
        pass

    def list_backup_files(self, node: str, storage: str, vmid: int | None = None) -> list[dict[str, Any]]:
        return []

    def download_backup_file(self, node: str, storage: str, volume: str) -> bytes:
        return b"mock-backup-data"

    def restore_vm_backup(self, node: str, storage: str, archive: str, vmid: int, **kw: Any) -> str:
        return f"UPID:{node}:restore:{vmid}"

    def restore_ct_backup(self, node: str, storage: str, archive: str, vmid: int, **kw: Any) -> str:
        return f"UPID:{node}:restore:{vmid}"

    def get_task_log(self, node: str, upid: str) -> list[dict[str, Any]]:
        return [{"t": "Task completed", "n": 1}]


class MockStorageService:
    """Fake S3 storage service."""

    async def create_bucket(self, bucket_name: str) -> dict[str, Any]:
        return {"bucket": bucket_name, "status": "created"}

    async def delete_bucket(self, bucket_name: str, force: bool = False) -> dict[str, Any]:
        return {"bucket": bucket_name, "status": "deleted"}

    async def list_buckets(self) -> list[dict[str, Any]]:
        return []

    async def list_objects(self, bucket_name: str, prefix: str = "") -> list[dict[str, Any]]:
        return []

    async def get_bucket_size(self, bucket_name: str) -> int:
        return 0

    async def upload_object(self, bucket_name: str, key: str, data: bytes, content_type: str = "") -> dict[str, Any]:
        return {"key": key, "size": len(data), "status": "uploaded"}

    async def download_object(self, bucket_name: str, key: str) -> bytes:
        return b"mock-file-content"

    async def delete_object(self, bucket_name: str, key: str) -> dict[str, Any]:
        return {"key": key, "status": "deleted"}

    async def generate_presigned_url(
        self,
        bucket_name: str,
        key: str,
        expires_in: int = 3600,
        method: str = "GET",
    ) -> str:
        return f"http://s3-mock/{bucket_name}/{key}?signature=mock&expires={expires_in}"


mock_proxmox = MockProxmoxClient()
mock_storage = MockStorageService()


@pytest.fixture
def mock_proxmox_client():
    return mock_proxmox


@pytest.fixture
def mock_storage_service():
    return mock_storage


# ---------------------------------------------------------------------------
# Rate limiter mock - always allows
# ---------------------------------------------------------------------------


async def _always_allow(*args, **kwargs):
    return True, 0


async def _always_allow_api(*args, **kwargs):
    return True, 999


# ---------------------------------------------------------------------------
# Test users
# ---------------------------------------------------------------------------

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        id=TEST_USER_ID,
        email="user@test.com",
        username="testuser",
        hashed_password=hash_password("testpassword"),
        full_name="Test User",
        role="member",
        is_active=True,
        auth_provider="local",
    )
    db_session.add(user)
    db_session.add(UserQuota(user_id=user.id))
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_admin(db_session: AsyncSession) -> User:
    admin = User(
        id=TEST_ADMIN_ID,
        email="admin@test.com",
        username="testadmin",
        hashed_password=hash_password("adminpassword"),
        full_name="Test Admin",
        role="admin",
        is_active=True,
        is_superuser=True,
        auth_provider="local",
    )
    db_session.add(admin)
    db_session.add(UserQuota(user_id=admin.id))
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


def make_token(user: User) -> str:
    return create_access_token({"sub": str(user.id)})


# ---------------------------------------------------------------------------
# Wired-up test client - overrides all external deps
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(db_session: AsyncSession, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient wired to the FastAPI app with mocked DB, Proxmox, S3, Redis."""
    import app.services.proxmox_client as pxm_mod
    import app.services.rate_limiter as rl_mod
    import app.services.storage_service as stg_mod

    # Swap singletons
    monkeypatch.setattr(pxm_mod, "proxmox_client", mock_proxmox)
    monkeypatch.setattr(stg_mod, "storage_service", mock_storage)
    monkeypatch.setattr(rl_mod, "check_action_rate_limit", _always_allow)
    monkeypatch.setattr(rl_mod, "check_api_rate_limit", _always_allow_api)
    monkeypatch.setattr(rl_mod, "check_rate_limit", _always_allow)

    # Patch Redis-based token revocation to avoid needing Redis in tests
    import app.core.security as sec_mod

    async def _not_revoked(_jti: str) -> bool:
        return False

    async def _not_revoked_before(_uid: str, _iat: float) -> bool:
        return False

    monkeypatch.setattr(sec_mod, "is_token_revoked", _not_revoked)
    monkeypatch.setattr(sec_mod, "is_user_tokens_revoked_before", _not_revoked_before)

    # Also patch storage_service in the storage router
    import app.routers.storage as storage_mod

    monkeypatch.setattr(storage_mod, "storage_service", mock_storage)

    # Patch volumes router so it uses the mock Proxmox client
    import app.routers.volumes as vol_mod

    monkeypatch.setattr(vol_mod, "_get_proxmox", lambda: mock_proxmox)

    from app.main import app

    # Override DB dependency
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def auth_client(client: AsyncClient, test_user: User) -> AsyncClient:
    """Test client with a valid user auth token pre-set."""
    token = make_token(test_user)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture
async def admin_client(client: AsyncClient, test_admin: User) -> AsyncClient:
    """Test client with a valid admin auth token pre-set."""
    token = make_token(test_admin)
    client.headers["Authorization"] = f"Bearer {token}"
    return client

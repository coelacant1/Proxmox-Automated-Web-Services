"""Cluster registry - manages ProxmoxClient and PBSClient instances for all configured clusters.

Usage:
    from app.services.cluster_registry import cluster_registry

    pve = cluster_registry.get_pve("main")        # specific cluster
    pve = cluster_registry.get_pve()               # default (first) cluster
    pbs = cluster_registry.get_pbs("main")
    ids = cluster_registry.list_cluster_ids()

Initialization:
    Call ``await cluster_registry.reload()`` once during application startup
    (FastAPI lifespan) and after any connection create/update/delete.
    Celery tasks should call ``await cluster_registry.reload()`` inside their
    async entry point if ``not cluster_registry.has_clusters()``.
"""

import json
import logging
from dataclasses import dataclass, field

from app.services.pbs_client import PBSClient
from app.services.proxmox_client import ProxmoxClient

logger = logging.getLogger(__name__)


@dataclass
class ClusterConfig:
    """Lightweight cluster metadata held in memory for admin/status queries.

    Credentials are NOT stored here; they live (encrypted) in the
    ``cluster_connections`` table and are passed directly to the PVE/PBS
    client instances on registration.
    """

    name: str
    host: str = ""
    port: int = 8006
    pbs_host: str = ""
    pbs_port: int = 8007
    pbs_datastore: str = "backups"
    extra: dict = field(default_factory=dict)


class NoClustersConfigured(RuntimeError):  # noqa: N818
    """Raised when a caller needs a Proxmox client but none are configured."""


class ClusterRegistry:
    """Manages ProxmoxClient + PBSClient instances for every configured cluster.

    Clients are loaded asynchronously from the ``cluster_connections`` table.
    Call ``await reload()`` at startup and after any connection CRUD.
    """

    def __init__(self) -> None:
        self._pve_clients: dict[str, ProxmoxClient] = {}
        self._pbs_clients: dict[str, PBSClient] = {}
        self._configs: dict[str, ClusterConfig] = {}
        self._default_cluster: str | None = None
        self._initialized = False

    def _ensure_init(self) -> None:
        """Guard used by sync accessors. Logs a warning if reload() was never called."""
        if not self._initialized:
            logger.warning(
                "Cluster registry accessed before reload(). "
                "Ensure await cluster_registry.reload() is called at startup."
            )
            self._initialized = True

    async def reload(self) -> bool:
        """Load (or reload) cluster connections from the database.

        Safe to call from FastAPI lifespan, async route handlers, and Celery tasks
        that run their own event loop. Returns True if at least one PVE client
        was registered.
        """
        self._pve_clients.clear()
        self._pbs_clients.clear()
        self._configs.clear()
        self._default_cluster = None

        try:
            from sqlalchemy import select

            from app.core.database import async_session
            from app.core.encryption import decrypt
            from app.models.models import ClusterConnection

            async with async_session() as db:
                result = await db.execute(
                    select(ClusterConnection)
                    .where(ClusterConnection.is_active.is_(True))
                    .order_by(ClusterConnection.created_at)
                )
                rows = result.scalars().all()

            if not rows:
                logger.warning("No active cluster connections found. Add one via Admin > Infrastructure > Connections.")
                self._initialized = True
                return False

            for conn in rows:
                name = conn.name
                conn_type = conn.conn_type
                host = conn.host
                port = conn.port
                token_id = conn.token_id or ""
                token_secret = decrypt(conn.token_secret_enc) if conn.token_secret_enc else ""
                password = decrypt(conn.password_enc) if conn.password_enc else ""
                fingerprint = conn.fingerprint or ""
                verify_ssl = conn.verify_ssl
                extra = json.loads(conn.extra_config) if conn.extra_config else {}
                console_user = conn.console_user or ""
                console_password = decrypt(conn.console_password_enc) if conn.console_password_enc else ""

                if conn_type == "pve":
                    cfg = ClusterConfig(name=name, host=host, port=port)
                    self._configs[name] = cfg
                    self._pve_clients[name] = ProxmoxClient(
                        host=host,
                        port=port,
                        token_id=token_id,
                        token_secret=token_secret,
                        verify_ssl=verify_ssl,
                        password=password,
                        console_user=console_user,
                        console_password=console_password,
                        cluster_name=name,
                    )
                    if self._default_cluster is None:
                        self._default_cluster = name
                    logger.info("Registered PVE cluster '%s' (%s:%d)", name, host, port)

                elif conn_type == "pbs":
                    datastore = extra.get("datastore", "backups")
                    pve_cluster = extra.get("pve_cluster", name)
                    self._pbs_clients[pve_cluster] = PBSClient(
                        host=host,
                        port=port,
                        token_id=token_id,
                        token_secret=token_secret,
                        fingerprint=fingerprint,
                        datastore=datastore,
                        verify_ssl=verify_ssl,
                        cluster_name=pve_cluster,
                    )
                    if pve_cluster in self._configs:
                        self._configs[pve_cluster].pbs_host = host
                        self._configs[pve_cluster].pbs_port = port
                        self._configs[pve_cluster].pbs_datastore = datastore
                    logger.info("Registered PBS '%s' (%s:%d)", name, host, port)

        except Exception as exc:
            logger.error("Cluster registry reload failed: %s", exc)
            self._initialized = True
            return False

        self._initialized = True
        return bool(self._pve_clients)

    @property
    def default_cluster(self) -> str:
        self._ensure_init()
        if self._default_cluster is None:
            raise NoClustersConfigured(
                "No Proxmox clusters configured. Add one via Admin > Infrastructure > Connections."
            )
        return self._default_cluster

    def _resolve_cluster_id(self, cluster_id: str | None) -> str:
        """Return a valid cluster id, falling back to the default.

        PAWS is now a single-cluster control plane (one PAWS instance per
        Proxmox cluster). Legacy rows in the database may still carry stale
        ``cluster_id`` values for clusters that have been removed or renamed;
        rather than 500ing, we transparently redirect them to the primary
        cluster and log a debug note. Callers that genuinely need "the only
        cluster we have" can pass ``None``.
        """
        self._ensure_init()
        if not self._pve_clients:
            raise NoClustersConfigured(
                "No Proxmox clusters configured. Add one via Admin > Infrastructure > Connections."
            )
        if not cluster_id:
            return self._default_cluster  # type: ignore[return-value]
        if cluster_id in self._pve_clients:
            return cluster_id
        logger.debug(
            "Unknown cluster_id '%s'; falling back to primary '%s'. This is normal during single-cluster migration.",
            cluster_id,
            self._default_cluster,
        )
        return self._default_cluster  # type: ignore[return-value]

    def get_pve(self, cluster_id: str | None = None) -> ProxmoxClient:
        """Return ProxmoxClient for the given cluster, or the primary cluster.

        Unknown cluster ids are transparently redirected to the primary
        (single-cluster consolidation). Raises ``NoClustersConfigured`` if no
        clusters are registered at all.
        """
        cid = self._resolve_cluster_id(cluster_id)
        return self._pve_clients[cid]

    def get_pbs(self, cluster_id: str | None = None) -> PBSClient:
        """Return PBSClient for the given cluster, or the primary.

        Raises ``KeyError`` only when PBS is not configured for the resolved
        cluster (PBS is optional per cluster).
        """
        cid = self._resolve_cluster_id(cluster_id)
        client = self._pbs_clients.get(cid)
        if client is None:
            raise KeyError(f"PBS not configured for cluster '{cid}'. Available: {list(self._pbs_clients)}")
        return client

    def get_config(self, cluster_id: str | None = None) -> ClusterConfig:
        """Return ClusterConfig for the given cluster, or the primary."""
        cid = self._resolve_cluster_id(cluster_id)
        return self._configs[cid]

    def get_all_pve(self) -> dict[str, ProxmoxClient]:
        """Return all ProxmoxClient instances keyed by cluster name."""
        self._ensure_init()
        return dict(self._pve_clients)

    def get_all_pbs(self) -> dict[str, PBSClient]:
        """Return all PBSClient instances keyed by cluster name."""
        self._ensure_init()
        return dict(self._pbs_clients)

    def list_cluster_ids(self) -> list[str]:
        """Return list of all configured cluster names."""
        self._ensure_init()
        return list(self._configs)

    def list_cluster_configs(self) -> list[ClusterConfig]:
        """Return all cluster configs (credentials excluded from repr)."""
        self._ensure_init()
        return list(self._configs.values())

    def has_clusters(self) -> bool:
        """Check if any clusters are configured without raising."""
        self._ensure_init()
        return bool(self._pve_clients)


cluster_registry = ClusterRegistry()

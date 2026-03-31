"""Cluster registry - manages ProxmoxClient and PBSClient instances for all configured clusters.

Usage:
    from app.services.cluster_registry import cluster_registry

    pve = cluster_registry.get_pve("main")        # specific cluster
    pve = cluster_registry.get_pve()               # default (first) cluster
    pbs = cluster_registry.get_pbs("main")
    ids = cluster_registry.list_cluster_ids()
"""

import json
import logging

from app.core.config import ClusterConfig, settings
from app.services.pbs_client import PBSClient
from app.services.proxmox_client import ProxmoxClient

logger = logging.getLogger(__name__)


class ClusterRegistry:
    """Manages ProxmoxClient + PBSClient instances for every configured cluster."""

    def __init__(self) -> None:
        self._pve_clients: dict[str, ProxmoxClient] = {}
        self._pbs_clients: dict[str, PBSClient] = {}
        self._configs: dict[str, ClusterConfig] = {}
        self._default_cluster: str | None = None
        self._initialized = False

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # Try DB-based connections first, then fall back to env
        if self._load_from_db():
            return

        configs = settings.get_cluster_configs()
        if not configs:
            logger.warning("No Proxmox clusters configured")
            return

        self._default_cluster = configs[0].name
        for cfg in configs:
            self._register_from_config(cfg)

    def _load_from_db(self) -> bool:
        """Load cluster connections from the database (synchronous, for init)."""
        try:
            from sqlalchemy import create_engine, text

            sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
            sync_url = sync_url.replace("postgresql+psycopg2", "postgresql")
            engine = create_engine(sync_url)

            with engine.connect() as conn:
                # Check if table exists
                row = conn.execute(
                    text("SELECT 1 FROM information_schema.tables WHERE table_name = 'cluster_connections'")
                ).fetchone()
                if not row:
                    return False

                rows = conn.execute(
                    text(
                        "SELECT name, conn_type, host, port, token_id, "
                        "token_secret_enc, password_enc, fingerprint, "
                        "verify_ssl, is_active, extra_config "
                        "FROM cluster_connections WHERE is_active = true "
                        "ORDER BY created_at"
                    )
                ).fetchall()

            engine.dispose()

            if not rows:
                return False

            from app.core.encryption import decrypt

            for r in rows:
                name = r[0]
                conn_type = r[1]
                host = r[2]
                port = r[3]
                token_id = r[4] or ""
                token_secret = decrypt(r[5]) if r[5] else ""
                password = decrypt(r[6]) if r[6] else ""
                fingerprint = r[7] or ""
                verify_ssl = r[8]
                extra = json.loads(r[10]) if r[10] else {}

                if conn_type == "pve":
                    cfg = ClusterConfig(
                        name=name,
                        host=host,
                        port=port,
                        token_id=token_id,
                        token_secret=token_secret,
                        verify_ssl=verify_ssl,
                        password=password,
                    )
                    self._configs[name] = cfg
                    self._pve_clients[name] = ProxmoxClient(
                        host=host,
                        port=port,
                        token_id=token_id,
                        token_secret=token_secret,
                        verify_ssl=verify_ssl,
                        password=password,
                        cluster_name=name,
                    )
                    if self._default_cluster is None:
                        self._default_cluster = name
                    logger.info("Registered PVE cluster '%s' from DB (%s:%d)", name, host, port)

                elif conn_type == "pbs":
                    datastore = extra.get("datastore", "backups")
                    # Find matching PVE cluster name or use PBS name
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
                    logger.info("Registered PBS '%s' from DB (%s:%d)", name, host, port)

            return bool(self._pve_clients)

        except Exception as exc:
            logger.debug("DB cluster load skipped: %s", exc)
            return False

    def _register_from_config(self, cfg: ClusterConfig) -> None:
        """Register a cluster from a ClusterConfig (env-based)."""
        self._configs[cfg.name] = cfg
        self._pve_clients[cfg.name] = ProxmoxClient(
            host=cfg.host,
            port=cfg.port,
            token_id=cfg.token_id,
            token_secret=cfg.token_secret,
            verify_ssl=cfg.verify_ssl,
            password=cfg.password,
            cluster_name=cfg.name,
        )
        self._pbs_clients[cfg.name] = PBSClient(
            host=cfg.pbs_host,
            port=cfg.pbs_port,
            token_id=cfg.pbs_token_id,
            token_secret=cfg.pbs_token_secret,
            fingerprint=cfg.pbs_fingerprint,
            datastore=cfg.pbs_datastore,
            verify_ssl=cfg.pbs_verify_ssl,
            cluster_name=cfg.name,
        )
        logger.info("Registered cluster '%s' (%s:%d)", cfg.name, cfg.host, cfg.port)

    def invalidate(self) -> None:
        """Clear all cached clients, forcing reload on next access."""
        self._pve_clients.clear()
        self._pbs_clients.clear()
        self._configs.clear()
        self._default_cluster = None
        self._initialized = False
        logger.info("Cluster registry invalidated, will reload on next access")

    @property
    def default_cluster(self) -> str:
        self._ensure_init()
        if self._default_cluster is None:
            raise RuntimeError("No Proxmox clusters configured")
        return self._default_cluster

    def get_pve(self, cluster_id: str | None = None) -> ProxmoxClient:
        """Return ProxmoxClient for the given cluster, or the default."""
        self._ensure_init()
        cid = cluster_id or self.default_cluster
        client = self._pve_clients.get(cid)
        if client is None:
            raise KeyError(f"Unknown cluster '{cid}'. Available: {list(self._pve_clients)}")
        return client

    def get_pbs(self, cluster_id: str | None = None) -> PBSClient:
        """Return PBSClient for the given cluster, or the default."""
        self._ensure_init()
        cid = cluster_id or self.default_cluster
        client = self._pbs_clients.get(cid)
        if client is None:
            raise KeyError(f"Unknown cluster '{cid}'. Available: {list(self._pbs_clients)}")
        return client

    def get_config(self, cluster_id: str | None = None) -> ClusterConfig:
        """Return ClusterConfig for the given cluster, or the default."""
        self._ensure_init()
        cid = cluster_id or self.default_cluster
        cfg = self._configs.get(cid)
        if cfg is None:
            raise KeyError(f"Unknown cluster '{cid}'")
        return cfg

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

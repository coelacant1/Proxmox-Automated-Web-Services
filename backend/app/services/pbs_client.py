"""Proxmox Backup Server (PBS) client service.

Wraps the PBS REST API for namespace management, backup listing, and usage queries.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class PBSClient:
    """PBS REST API client - singleton."""

    _instance: "PBSClient | None" = None

    def __new__(cls) -> "PBSClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def configured(self) -> bool:
        return bool(settings.pbs_host)

    @property
    def _base_url(self) -> str:
        return f"https://{settings.pbs_host}:{settings.pbs_port}/api2/json"

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"PBSAPIToken={settings.pbs_token_id}:{settings.pbs_token_secret}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(verify=settings.pbs_verify_ssl, timeout=30) as client:
            r = await client.request(method, f"{self._base_url}{path}", headers=self._auth_headers, **kwargs)
            r.raise_for_status()
            data = r.json()
            return data.get("data", data)

    async def _stream_request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Return a streaming response (caller must close)."""
        client = httpx.AsyncClient(verify=settings.pbs_verify_ssl, timeout=120)
        r = await client.send(
            client.build_request(method, f"{self._base_url}{path}", headers=self._auth_headers, **kwargs),
            stream=True,
        )
        r.raise_for_status()
        return r

    # --- Datastore Operations ---

    async def list_datastores(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/admin/datastore")

    async def get_datastore_usage(self, datastore: str) -> dict[str, Any]:
        return await self._request("GET", f"/admin/datastore/{datastore}/status")

    # --- Namespace Operations ---

    async def list_namespaces(self, datastore: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/admin/datastore/{datastore}/namespace")

    async def create_namespace(self, datastore: str, namespace: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/admin/datastore/{datastore}/namespace",
            json={"name": namespace},
        )

    async def ensure_namespace(self, datastore: str, namespace: str) -> None:
        """Create namespace if it does not exist."""
        try:
            existing = await self.list_namespaces(datastore)
            for ns in existing:
                if ns.get("ns") == namespace:
                    return
            await self.create_namespace(datastore, namespace)
            logger.info("Created PBS namespace %s/%s", datastore, namespace)
        except Exception:
            logger.warning("Failed to ensure PBS namespace %s/%s", datastore, namespace, exc_info=True)

    async def delete_namespace(self, datastore: str, namespace: str, delete_groups: bool = True) -> dict[str, Any]:
        params: dict[str, str] = {"ns": namespace, "delete-groups": str(delete_groups).lower()}
        return await self._request(
            "DELETE",
            f"/admin/datastore/{datastore}/namespace",
            params=params,
        )

    async def get_namespace_usage(self, datastore: str, namespace: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/admin/datastore/{datastore}/status",
            params={"ns": namespace},
        )

    # --- Backup Operations ---

    async def list_backups(self, datastore: str, namespace: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if namespace:
            params["ns"] = namespace
        return await self._request(
            "GET",
            f"/admin/datastore/{datastore}/snapshots",
            params=params,
        )

    async def delete_backup(
        self,
        datastore: str,
        backup_type: str,
        backup_id: str,
        backup_time: int,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "backup-type": backup_type,
            "backup-id": backup_id,
            "backup-time": backup_time,
        }
        if namespace:
            params["ns"] = namespace
        return await self._request(
            "DELETE",
            f"/admin/datastore/{datastore}/snapshots",
            params=params,
        )

    # --- File Restore ---

    async def list_backup_files(
        self,
        datastore: str,
        backup_type: str,
        backup_id: str,
        backup_time: int,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """List top-level files/archives in a backup snapshot."""
        params: dict[str, Any] = {
            "backup-type": backup_type,
            "backup-id": backup_id,
            "backup-time": backup_time,
        }
        if namespace:
            params["ns"] = namespace
        return await self._request(
            "GET",
            f"/admin/datastore/{datastore}/files",
            params=params,
        )

    async def catalog_listing(
        self,
        datastore: str,
        backup_type: str,
        backup_id: str,
        backup_time: int,
        filepath: str,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Browse directory contents inside a pxar archive."""
        params: dict[str, Any] = {
            "backup-type": backup_type,
            "backup-id": backup_id,
            "backup-time": backup_time,
            "filepath": filepath,
        }
        if namespace:
            params["ns"] = namespace
        return await self._request(
            "GET",
            f"/admin/datastore/{datastore}/catalog",
            params=params,
        )

    async def download_file(
        self,
        datastore: str,
        backup_type: str,
        backup_id: str,
        backup_time: int,
        filepath: str,
        namespace: str | None = None,
    ) -> httpx.Response:
        """Stream a file download from a pxar archive."""
        params: dict[str, Any] = {
            "backup-type": backup_type,
            "backup-id": backup_id,
            "backup-time": backup_time,
            "filepath": filepath,
        }
        if namespace:
            params["ns"] = namespace
        return await self._stream_request(
            "GET",
            f"/admin/datastore/{datastore}/pxar-file-download",
            params=params,
        )

    # --- Prune / Garbage Collection ---

    async def run_prune(self, datastore: str, namespace: str | None = None, **retention: Any) -> dict[str, Any]:
        data: dict[str, Any] = {**retention}
        if namespace:
            data["ns"] = namespace
        return await self._request(
            "POST",
            f"/admin/datastore/{datastore}/prune",
            json=data,
        )

    async def run_gc(self, datastore: str) -> dict[str, Any]:
        return await self._request("POST", f"/admin/datastore/{datastore}/gc")

    # --- Verify ---

    async def verify_backup(
        self,
        datastore: str,
        backup_type: str,
        backup_id: str,
        backup_time: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/admin/datastore/{datastore}/verify",
            json={
                "backup-type": backup_type,
                "backup-id": backup_id,
                "backup-time": backup_time,
            },
        )


pbs_client = PBSClient()

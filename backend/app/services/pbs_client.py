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
    def _base_url(self) -> str:
        host = getattr(settings, "pbs_host", "localhost")
        port = getattr(settings, "pbs_port", 8007)
        return f"https://{host}:{port}/api2/json"

    @property
    def _auth_headers(self) -> dict[str, str]:
        token_id = getattr(settings, "pbs_token_id", "root@pam!paws")
        token_secret = getattr(settings, "pbs_token_secret", "")
        return {"Authorization": f"PBSAPIToken={token_id}:{token_secret}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            r = await client.request(method, f"{self._base_url}{path}", headers=self._auth_headers, **kwargs)
            r.raise_for_status()
            data = r.json()
            return data.get("data", data)

    # --- Datastore Operations ---

    async def list_datastores(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/admin/datastore")

    async def get_datastore_usage(self, datastore: str) -> dict[str, Any]:
        return await self._request("GET", f"/admin/datastore/{datastore}/status")

    # --- Namespace Operations ---

    async def list_namespaces(self, datastore: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/admin/datastore/{datastore}/namespace")

    async def create_namespace(self, datastore: str, namespace: str) -> dict[str, Any]:
        return await self._request("POST", f"/admin/datastore/{datastore}/namespace", json={"name": namespace})

    async def delete_namespace(
        self, datastore: str, namespace: str, delete_groups: bool = True
    ) -> dict[str, Any]:
        params = {"ns": namespace, "delete-groups": str(delete_groups).lower()}
        return await self._request("DELETE", f"/admin/datastore/{datastore}/namespace", params=params)

    async def get_namespace_usage(self, datastore: str, namespace: str) -> dict[str, Any]:
        return await self._request("GET", f"/admin/datastore/{datastore}/status", params={"ns": namespace})

    # --- Backup Operations ---

    async def list_backups(self, datastore: str, namespace: str | None = None) -> list[dict[str, Any]]:
        params = {}
        if namespace:
            params["ns"] = namespace
        return await self._request("GET", f"/admin/datastore/{datastore}/snapshots", params=params)

    async def get_backup_details(
        self, datastore: str, backup_type: str, backup_id: str, backup_time: str
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/admin/datastore/{datastore}/snapshots/{backup_type}/{backup_id}/{backup_time}",
        )

    async def delete_backup(
        self, datastore: str, backup_type: str, backup_id: str, backup_time: str
    ) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            f"/admin/datastore/{datastore}/snapshots/{backup_type}/{backup_id}/{backup_time}",
        )

    # --- Prune / Garbage Collection ---

    async def run_prune(self, datastore: str, namespace: str | None = None, **retention: Any) -> dict[str, Any]:
        data: dict[str, Any] = {**retention}
        if namespace:
            data["ns"] = namespace
        return await self._request("POST", f"/admin/datastore/{datastore}/prune", json=data)

    async def run_gc(self, datastore: str) -> dict[str, Any]:
        return await self._request("POST", f"/admin/datastore/{datastore}/gc")

    # --- Verify ---

    async def verify_backup(
        self, datastore: str, backup_type: str, backup_id: str, backup_time: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/admin/datastore/{datastore}/verify",
            json={"backup-type": backup_type, "backup-id": backup_id, "backup-time": backup_time},
        )


pbs_client = PBSClient()

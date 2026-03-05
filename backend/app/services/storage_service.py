"""MinIO / S3-compatible object storage service layer."""

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """
    Wraps MinIO admin and S3 operations.
    Uses MinIO's admin API for bucket/user management and presigned URL generation.
    For full S3 compatibility, users should connect directly with their credentials.
    """

    def __init__(self):
        self.endpoint = settings.minio_endpoint
        self.access_key = settings.minio_root_user
        self.secret_key = settings.minio_root_password
        self.region = settings.minio_region

    @property
    def _base_url(self) -> str:
        scheme = "https" if settings.minio_use_ssl else "http"
        return f"{scheme}://{self.endpoint}"

    async def create_bucket(self, bucket_name: str) -> dict[str, Any]:
        """Create a new S3 bucket via MinIO."""
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self._base_url}/{bucket_name}",
                headers=self._auth_headers("PUT", bucket_name),
            )
            if response.status_code in (200, 409):  # 409 = already exists
                return {"bucket": bucket_name, "status": "created"}
            response.raise_for_status()
            return {"bucket": bucket_name, "status": "created"}

    async def delete_bucket(self, bucket_name: str) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self._base_url}/{bucket_name}",
                headers=self._auth_headers("DELETE", bucket_name),
            )
            response.raise_for_status()
            return {"bucket": bucket_name, "status": "deleted"}

    async def list_buckets(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/",
                headers=self._auth_headers("GET", ""),
            )
            response.raise_for_status()
            # Parse XML response (simplified)
            return self._parse_bucket_list(response.text)

    async def list_objects(self, bucket_name: str, prefix: str = "") -> list[dict[str, Any]]:
        params = {"list-type": "2"}
        if prefix:
            params["prefix"] = prefix
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/{bucket_name}",
                params=params,
                headers=self._auth_headers("GET", bucket_name),
            )
            response.raise_for_status()
            return self._parse_object_list(response.text)

    async def get_bucket_size(self, bucket_name: str) -> int:
        """Approximate bucket size in bytes."""
        objects = await self.list_objects(bucket_name)
        return sum(obj.get("size", 0) for obj in objects)

    async def upload_object(
        self, bucket_name: str, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self._base_url}/{bucket_name}/{key}",
                content=data,
                headers={**self._auth_headers("PUT", f"{bucket_name}/{key}"), "Content-Type": content_type},
            )
            response.raise_for_status()
            return {"key": key, "size": len(data), "status": "uploaded"}

    async def download_object(self, bucket_name: str, key: str) -> bytes:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/{bucket_name}/{key}",
                headers=self._auth_headers("GET", f"{bucket_name}/{key}"),
            )
            response.raise_for_status()
            return response.content

    async def delete_object(self, bucket_name: str, key: str) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self._base_url}/{bucket_name}/{key}",
                headers=self._auth_headers("DELETE", f"{bucket_name}/{key}"),
            )
            response.raise_for_status()
            return {"key": key, "status": "deleted"}

    def generate_presigned_url(
        self, bucket_name: str, key: str, expires_in: int = 3600, method: str = "GET"
    ) -> str:
        """Generate a presigned URL for temporary access."""
        import hashlib
        import hmac
        import time

        timestamp = int(time.time())
        expiry = timestamp + expires_in
        string_to_sign = f"{method}\n/{bucket_name}/{key}\n{expiry}"
        signature = hmac.new(
            self.secret_key.encode(), string_to_sign.encode(), hashlib.sha256
        ).hexdigest()
        scheme = "https" if settings.minio_use_ssl else "http"
        return (
            f"{scheme}://{self.endpoint}/{bucket_name}/{key}"
            f"?X-Amz-Expires={expires_in}&X-Amz-Signature={signature}"
            f"&X-Amz-Date={timestamp}"
        )

    def _auth_headers(self, method: str, resource: str) -> dict[str, str]:
        """Generate basic auth headers. In production, use proper AWS Sig V4."""
        import base64

        credentials = base64.b64encode(f"{self.access_key}:{self.secret_key}".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}

    @staticmethod
    def _parse_bucket_list(xml_text: str) -> list[dict[str, Any]]:
        """Simple XML parser for bucket listing."""
        import re

        buckets = []
        for match in re.finditer(r"<Name>(.*?)</Name>", xml_text):
            buckets.append({"name": match.group(1)})
        return buckets

    @staticmethod
    def _parse_object_list(xml_text: str) -> list[dict[str, Any]]:
        """Simple XML parser for object listing."""
        import re

        objects = []
        for key_match in re.finditer(r"<Key>(.*?)</Key>", xml_text):
            obj: dict[str, Any] = {"key": key_match.group(1)}
            size_match = re.search(rf"<Key>{re.escape(obj['key'])}</Key>.*?<Size>(\d+)</Size>", xml_text, re.DOTALL)
            if size_match:
                obj["size"] = int(size_match.group(1))
            objects.append(obj)
        return objects


storage_service = StorageService()

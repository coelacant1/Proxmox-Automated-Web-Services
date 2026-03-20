"""S3-compatible object storage service (Ceph RadosGW)."""

import logging
from typing import Any

import aioboto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """S3-compatible storage operations via aioboto3 (works with Ceph RadosGW, AWS S3, MinIO)."""

    def __init__(self):
        self._endpoint_url = settings.s3_endpoint_url
        self._access_key = settings.s3_access_key
        self._secret_key = settings.s3_secret_key
        self._region = settings.s3_region
        self._session = aioboto3.Session()

    def _client(self):
        """Return an async context-managed S3 client."""
        return self._session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            config=BotoConfig(signature_version="s3v4"),
        )

    async def create_bucket(self, bucket_name: str) -> dict[str, Any]:
        async with self._client() as s3:
            try:
                await s3.create_bucket(Bucket=bucket_name)
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    pass
                else:
                    raise
            return {"bucket": bucket_name, "status": "created"}

    async def delete_bucket(self, bucket_name: str, force: bool = False) -> dict[str, Any]:
        async with self._client() as s3:
            if force:
                # Delete all objects before removing the bucket
                paginator = s3.get_paginator("list_objects_v2")
                async for page in paginator.paginate(Bucket=bucket_name):
                    objects = page.get("Contents", [])
                    if objects:
                        await s3.delete_objects(
                            Bucket=bucket_name,
                            Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
                        )
            await s3.delete_bucket(Bucket=bucket_name)
            return {"bucket": bucket_name, "status": "deleted"}

    async def list_buckets(self) -> list[dict[str, Any]]:
        async with self._client() as s3:
            resp = await s3.list_buckets()
            return [{"name": b["Name"]} for b in resp.get("Buckets", [])]

    async def list_objects(
        self, bucket_name: str, prefix: str = ""
    ) -> list[dict[str, Any]]:
        async with self._client() as s3:
            params: dict[str, Any] = {"Bucket": bucket_name}
            if prefix:
                params["Prefix"] = prefix
            resp = await s3.list_objects_v2(**params)
            return [
                {"key": obj["Key"], "size": obj.get("Size", 0)}
                for obj in resp.get("Contents", [])
            ]

    async def get_bucket_size(self, bucket_name: str) -> int:
        objects = await self.list_objects(bucket_name)
        return sum(obj.get("size", 0) for obj in objects)

    async def upload_object(
        self,
        bucket_name: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        async with self._client() as s3:
            await s3.put_object(
                Bucket=bucket_name, Key=key, Body=data, ContentType=content_type
            )
            return {"key": key, "size": len(data), "status": "uploaded"}

    async def download_object(self, bucket_name: str, key: str) -> bytes:
        async with self._client() as s3:
            resp = await s3.get_object(Bucket=bucket_name, Key=key)
            return await resp["Body"].read()

    async def delete_object(self, bucket_name: str, key: str) -> dict[str, Any]:
        async with self._client() as s3:
            await s3.delete_object(Bucket=bucket_name, Key=key)
            return {"key": key, "status": "deleted"}

    async def generate_presigned_url(
        self,
        bucket_name: str,
        key: str,
        expires_in: int = 3600,
        method: str = "GET",
    ) -> str:
        client_method = "get_object" if method.upper() == "GET" else "put_object"
        async with self._client() as s3:
            return await s3.generate_presigned_url(
                ClientMethod=client_method,
                Params={"Bucket": bucket_name, "Key": key},
                ExpiresIn=expires_in,
            )


storage_service = StorageService()

"""Object storage (S3-compatible / Ceph RadosGW) endpoints.

Manages storage buckets with proper quota enforcement, versioning, and tagging.
"""

import json
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import StorageBucket, User, UserQuota
from app.services.audit_service import log_action
from app.services.storage_service import storage_service

router = APIRouter(prefix="/api/storage", tags=["storage"])

BUCKET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")


@router.get("/s3-info")
async def get_s3_connection_info(user: User = Depends(get_current_active_user)):
    """Return S3 endpoint info so users can configure CLI tools and SDKs."""
    from app.core.config_resolver import get_config_value

    return {
        "endpoint_url": await get_config_value("s3_endpoint_url"),
        "region": await get_config_value("s3_region"),
        "note": "Use your PAWS API key as the Access Key. Generate one from Account > API Keys.",
    }


@router.get("/quota")
async def get_storage_quota(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Return current user's storage quota and usage."""
    quota = await _get_storage_quota(db, user.id)
    count_result = await db.execute(select(func.count(StorageBucket.id)).where(StorageBucket.owner_id == user.id))
    size_result = await db.execute(
        select(func.coalesce(func.sum(StorageBucket.size_bytes), 0)).where(StorageBucket.owner_id == user.id)
    )
    bucket_count = count_result.scalar() or 0
    total_bytes = size_result.scalar() or 0
    return {
        "buckets_used": bucket_count,
        "buckets_max": quota["max_buckets"],
        "storage_used_bytes": total_bytes,
        "storage_used_gb": round(total_bytes / 1_073_741_824, 3),
        "storage_max_gb": quota["max_storage_gb"],
    }


class BucketCreateRequest(BaseModel):
    name: str
    versioning_enabled: bool = False
    is_public: bool = False
    tags: dict[str, str] | None = None

    @field_validator("name")
    @classmethod
    def validate_bucket_name(cls, v: str) -> str:
        if not BUCKET_NAME_PATTERN.match(v):
            raise ValueError("Bucket name must be 3-63 chars, lowercase alphanumeric, dots, hyphens")
        if ".." in v or ".-" in v or "-." in v:
            raise ValueError("Bucket name cannot contain consecutive dots/hyphens")
        return v


class BucketUpdateRequest(BaseModel):
    versioning_enabled: bool | None = None
    is_public: bool | None = None
    tags: dict[str, str] | None = None


@router.get("/buckets")
async def list_buckets(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(StorageBucket).where(StorageBucket.owner_id == user.id).order_by(StorageBucket.created_at.desc())
    )
    buckets = result.scalars().all()
    return [
        {
            "id": str(b.id),
            "name": b.name,
            "region": b.region,
            "versioning_enabled": b.versioning_enabled,
            "size_bytes": b.size_bytes,
            "total_size": b.size_bytes,
            "object_count": b.object_count,
            "is_public": b.is_public,
            "tags": json.loads(b.tags) if b.tags else {},
            "created_at": str(b.created_at),
        }
        for b in buckets
    ]


@router.post("/buckets", status_code=status.HTTP_201_CREATED)
async def create_bucket(
    body: BucketCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    quota = await _get_storage_quota(db, user.id)
    count = await db.execute(select(func.count(StorageBucket.id)).where(StorageBucket.owner_id == user.id))
    current_count = count.scalar() or 0
    if current_count >= quota["max_buckets"]:
        raise HTTPException(status_code=403, detail=f"Bucket quota exceeded ({quota['max_buckets']} max)")

    existing = await db.execute(select(StorageBucket).where(StorageBucket.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Bucket name '{body.name}' already exists")

    try:
        await storage_service.create_bucket(body.name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to create bucket: {e}")

    bucket = StorageBucket(
        owner_id=user.id,
        name=body.name,
        versioning_enabled=body.versioning_enabled,
        is_public=body.is_public,
        tags=json.dumps(body.tags) if body.tags else None,
    )
    db.add(bucket)
    await db.commit()
    await log_action(db, user.id, "bucket_create", "bucket", bucket.id)

    return {"id": str(bucket.id), "name": bucket.name, "status": "created"}


@router.get("/buckets/{bucket_id}")
async def get_bucket(
    bucket_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    return {
        "id": str(bucket.id),
        "name": bucket.name,
        "region": bucket.region,
        "versioning_enabled": bucket.versioning_enabled,
        "size_bytes": bucket.size_bytes,
        "total_size": bucket.size_bytes,
        "object_count": bucket.object_count,
        "is_public": bucket.is_public,
        "tags": json.loads(bucket.tags) if bucket.tags else {},
        "created_at": str(bucket.created_at),
    }


@router.patch("/buckets/{bucket_id}")
async def update_bucket(
    bucket_id: str,
    body: BucketUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    bucket = await _get_user_bucket(db, user.id, bucket_id)

    if body.versioning_enabled is not None:
        bucket.versioning_enabled = body.versioning_enabled
    if body.is_public is not None:
        bucket.is_public = body.is_public
    if body.tags is not None:
        bucket.tags = json.dumps(body.tags)

    await db.commit()
    return {"status": "updated"}


@router.delete("/buckets/{bucket_id}")
async def delete_bucket(
    bucket_id: str,
    force: bool = Query(False, description="Force delete non-empty bucket"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    bucket = await _get_user_bucket(db, user.id, bucket_id)

    if bucket.object_count > 0 and not force:
        raise HTTPException(status_code=409, detail="Bucket is not empty. Use force=true to delete.")

    try:
        await storage_service.delete_bucket(bucket.name, force=force)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to delete bucket: {e}")

    await db.delete(bucket)
    await db.commit()
    await log_action(db, user.id, "bucket_delete", "bucket", bucket.id)
    return {"status": "deleted"}


@router.get("/buckets/{bucket_id}/objects")
async def list_objects(
    bucket_id: str,
    prefix: str = "",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    try:
        objects = await storage_service.list_objects(bucket.name, prefix)
        return {"objects": objects, "prefix": prefix}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Object Metadata (must be before {key:path} catch-all routes) ---


class ObjectMetadataRequest(BaseModel):
    metadata: dict[str, str]


@router.get("/buckets/{bucket_id}/objects/{key:path}/metadata")
async def get_object_metadata(
    bucket_id: str,
    key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get metadata for an object."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    tags = json.loads(bucket.tags) if bucket.tags else {}
    meta_key = f"__meta:{key}"
    metadata = json.loads(tags.get(meta_key, "{}"))
    return {
        "bucket_id": str(bucket.id),
        "key": key,
        "metadata": metadata,
    }


@router.put("/buckets/{bucket_id}/objects/{key:path}/metadata")
async def set_object_metadata(
    bucket_id: str,
    key: str,
    body: ObjectMetadataRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Set custom metadata on an object. Max 2KB total."""
    meta_str = json.dumps(body.metadata)
    if len(meta_str) > 2048:
        raise HTTPException(status_code=400, detail="Metadata exceeds 2KB limit")

    bucket = await _get_user_bucket(db, user.id, bucket_id)
    tags = json.loads(bucket.tags) if bucket.tags else {}
    tags[f"__meta:{key}"] = meta_str
    bucket.tags = json.dumps(tags)
    await db.commit()
    return {"status": "updated", "key": key}


# --- Object CRUD ---


@router.put("/buckets/{bucket_id}/objects/{key:path}")
async def upload_object(
    bucket_id: str,
    key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    request: Request = None,
):
    """Upload an object to a bucket."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)

    # Check storage quota
    quota = await _get_storage_quota(db, user.id)
    if bucket.size_bytes >= quota["max_storage_gb"] * 1_073_741_824:
        raise HTTPException(status_code=403, detail="Storage quota exceeded")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Request body is empty")

    content_type = request.headers.get("content-type", "application/octet-stream")
    try:
        result = await storage_service.upload_object(bucket.name, key, body, content_type)
        bucket.object_count += 1
        bucket.size_bytes += len(body)
        await db.commit()
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/buckets/{bucket_id}/objects/{key:path}")
async def download_object(
    bucket_id: str,
    key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Download an object from a bucket."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    try:
        data = await storage_service.download_object(bucket.name, key)
        from fastapi.responses import Response

        return Response(content=data, media_type="application/octet-stream")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/buckets/{bucket_id}/objects/{key:path}")
async def delete_object(
    bucket_id: str,
    key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Delete an object from a bucket."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    try:
        result = await storage_service.delete_object(bucket.name, key)
        bucket.object_count = max(0, bucket.object_count - 1)
        await db.commit()
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class PresignedUrlRequest(BaseModel):
    key: str
    expires_in: int = 3600
    method: str = "GET"

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v.upper() not in ("GET", "PUT"):
            raise ValueError("Method must be GET or PUT")
        return v.upper()

    @field_validator("expires_in")
    @classmethod
    def validate_expires(cls, v: int) -> int:
        if v < 60 or v > 604800:
            raise ValueError("Expiry must be 60-604800 seconds (7 days max)")
        return v


@router.post("/buckets/{bucket_id}/presign")
@router.post("/buckets/{bucket_id}/presigned")
async def generate_presigned_url(
    bucket_id: str,
    body: PresignedUrlRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Generate a presigned URL for temporary object access."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    url = await storage_service.generate_presigned_url(bucket.name, body.key, body.expires_in, body.method)
    return {"url": url, "method": body.method, "expires_in": body.expires_in}


# --- Access Policies ---


class BucketPolicyRequest(BaseModel):
    policy: dict  # JSON policy document (simplified IAM-style)


@router.put("/buckets/{bucket_id}/policy")
async def set_bucket_policy(
    bucket_id: str,
    body: BucketPolicyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Set a bucket access policy."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    bucket.tags = json.dumps(
        {
            **json.loads(bucket.tags or "{}"),
            "__policy": json.dumps(body.policy),
        }
    )
    await db.commit()
    return {"status": "policy_set"}


@router.get("/buckets/{bucket_id}/policy")
async def get_bucket_policy(
    bucket_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get bucket access policy."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    tags = json.loads(bucket.tags or "{}")
    policy = json.loads(tags.get("__policy", "{}"))
    return {"bucket_id": str(bucket.id), "policy": policy}


@router.delete("/buckets/{bucket_id}/policy")
async def delete_bucket_policy(
    bucket_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Remove bucket access policy."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    tags = json.loads(bucket.tags or "{}")
    tags.pop("__policy", None)
    bucket.tags = json.dumps(tags)
    await db.commit()
    return {"status": "policy_deleted"}


# --- Encryption ---


class BucketEncryptionRequest(BaseModel):
    algorithm: str = "AES256"  # AES256 or aws:kms


@router.put("/buckets/{bucket_id}/encryption")
async def set_bucket_encryption(
    bucket_id: str,
    body: BucketEncryptionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Enable server-side encryption on a bucket."""
    if body.algorithm not in ("AES256", "aws:kms"):
        raise HTTPException(status_code=400, detail="Algorithm must be AES256 or aws:kms")

    bucket = await _get_user_bucket(db, user.id, bucket_id)
    tags = json.loads(bucket.tags or "{}")
    tags["__encryption"] = body.algorithm
    bucket.tags = json.dumps(tags)
    await db.commit()
    return {"status": "encryption_enabled", "algorithm": body.algorithm}


@router.get("/buckets/{bucket_id}/encryption")
async def get_bucket_encryption(
    bucket_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get bucket encryption settings."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    tags = json.loads(bucket.tags or "{}")
    algo = tags.get("__encryption")
    return {
        "bucket_id": str(bucket.id),
        "encryption_enabled": algo is not None,
        "algorithm": algo,
    }


# --- Metrics ---


@router.get("/buckets/{bucket_id}/metrics")
async def get_bucket_metrics(
    bucket_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get storage metrics for a bucket."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    quota = await _get_storage_quota(db, user.id)
    return {
        "bucket_id": str(bucket.id),
        "name": bucket.name,
        "size_bytes": bucket.size_bytes,
        "object_count": bucket.object_count,
        "quota_used_gb": round(bucket.size_bytes / 1_073_741_824, 3),
        "quota_max_gb": quota["max_storage_gb"],
        "versioning_enabled": bucket.versioning_enabled,
    }


# --- Folders ---


@router.put("/buckets/{bucket_id}/folders/{folder_path:path}")
async def create_folder(
    bucket_id: str,
    folder_path: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Create a folder (prefix) in a bucket."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    key = folder_path.rstrip("/") + "/"
    try:
        await storage_service.upload_object(bucket.name, key, b"", "application/x-directory")
        return {"status": "created", "folder": key}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Object Copy/Move ---


class ObjectCopyRequest(BaseModel):
    source_key: str
    destination_key: str
    destination_bucket_id: str | None = None


@router.post("/buckets/{bucket_id}/objects/copy")
async def copy_object(
    bucket_id: str,
    body: ObjectCopyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Copy an object within or between buckets."""
    src_bucket = await _get_user_bucket(db, user.id, bucket_id)
    dst_bucket_id = body.destination_bucket_id or bucket_id
    dst_bucket = await _get_user_bucket(db, user.id, dst_bucket_id)

    try:
        data = await storage_service.download_object(src_bucket.name, body.source_key)
        await storage_service.upload_object(dst_bucket.name, body.destination_key, data)
        dst_bucket.object_count += 1
        dst_bucket.size_bytes += len(data)
        await db.commit()
        return {
            "status": "copied",
            "source": f"{src_bucket.name}/{body.source_key}",
            "destination": f"{dst_bucket.name}/{body.destination_key}",
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/buckets/{bucket_id}/objects/move")
async def move_object(
    bucket_id: str,
    body: ObjectCopyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Move an object (copy + delete source)."""
    src_bucket = await _get_user_bucket(db, user.id, bucket_id)
    dst_bucket_id = body.destination_bucket_id or bucket_id
    dst_bucket = await _get_user_bucket(db, user.id, dst_bucket_id)

    try:
        data = await storage_service.download_object(src_bucket.name, body.source_key)
        await storage_service.upload_object(dst_bucket.name, body.destination_key, data)
        await storage_service.delete_object(src_bucket.name, body.source_key)

        if src_bucket.id != dst_bucket.id:
            src_bucket.object_count = max(0, src_bucket.object_count - 1)
            src_bucket.size_bytes = max(0, src_bucket.size_bytes - len(data))
            dst_bucket.object_count += 1
            dst_bucket.size_bytes += len(data)

        await db.commit()
        return {
            "status": "moved",
            "source": f"{src_bucket.name}/{body.source_key}",
            "destination": f"{dst_bucket.name}/{body.destination_key}",
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Bucket Detail/Settings ---


class BucketSettingsUpdate(BaseModel):
    description: str | None = None
    max_size_gib: float | None = None
    tags: dict[str, str] | None = None


@router.patch("/buckets/{bucket_id}/settings")
async def update_bucket_settings(
    bucket_id: str,
    body: BucketSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Update bucket settings (description, max_size, tags)."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    existing_tags = json.loads(bucket.tags) if bucket.tags else {}

    if body.description is not None:
        existing_tags["__description"] = body.description
    if body.max_size_gib is not None:
        existing_tags["__max_size_gib"] = str(body.max_size_gib)
    if body.tags is not None:
        # Merge user tags (skip reserved keys)
        for k, v in body.tags.items():
            if not k.startswith("__"):
                existing_tags[k] = v

    bucket.tags = json.dumps(existing_tags)
    await db.commit()
    return {"status": "updated", "bucket_id": str(bucket.id)}


@router.get("/buckets/{bucket_id}/detail")
async def get_bucket_detail(
    bucket_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get full bucket details including settings and policies."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    tags = json.loads(bucket.tags) if bucket.tags else {}
    policy = json.loads(tags.get("__policy", "{}"))
    encryption = json.loads(tags.get("__encryption", "{}"))

    return {
        "id": str(bucket.id),
        "name": bucket.name,
        "is_public": bucket.is_public,
        "versioning_enabled": bucket.versioning_enabled,
        "size_bytes": bucket.size_bytes,
        "object_count": bucket.object_count,
        "description": tags.get("__description", ""),
        "max_size_gib": float(tags.get("__max_size_gib", "0")),
        "policy": policy,
        "encryption": encryption,
        "user_tags": {k: v for k, v in tags.items() if not k.startswith("__")},
        "created_at": str(bucket.created_at),
    }


# --- Bucket Sharing ---


class BucketShareRequest(BaseModel):
    target_user_id: str
    permission: str = "read"  # read, write, admin


@router.post("/buckets/{bucket_id}/shares")
async def share_bucket(
    bucket_id: str,
    body: BucketShareRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Share a bucket with another user."""
    if body.permission not in ("read", "write", "admin"):
        raise HTTPException(status_code=400, detail="Permission must be read, write, or admin")

    bucket = await _get_user_bucket(db, user.id, bucket_id)
    tags = json.loads(bucket.tags) if bucket.tags else {}
    shares = json.loads(tags.get("__shares", "{}"))
    shares[body.target_user_id] = body.permission
    tags["__shares"] = json.dumps(shares)
    bucket.tags = json.dumps(tags)
    await db.commit()
    await log_action(db, user.id, "bucket_share", "storage", bucket.id, details={"shared_with": body.target_user_id})
    return {"status": "shared", "target_user_id": body.target_user_id, "permission": body.permission}


@router.delete("/buckets/{bucket_id}/shares/{target_user_id}")
async def revoke_bucket_share(
    bucket_id: str,
    target_user_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Revoke a bucket share."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    tags = json.loads(bucket.tags) if bucket.tags else {}
    shares = json.loads(tags.get("__shares", "{}"))
    shares.pop(target_user_id, None)
    tags["__shares"] = json.dumps(shares)
    bucket.tags = json.dumps(tags)
    await db.commit()
    return {"status": "revoked", "target_user_id": target_user_id}


@router.get("/buckets/{bucket_id}/shares")
async def list_bucket_shares(
    bucket_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List all shares for a bucket."""
    bucket = await _get_user_bucket(db, user.id, bucket_id)
    tags = json.loads(bucket.tags) if bucket.tags else {}
    shares = json.loads(tags.get("__shares", "{}"))
    return [{"user_id": uid, "permission": perm} for uid, perm in shares.items()]


@router.get("/shared-with-me")
async def list_shared_buckets(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List buckets shared with the current user."""
    user_id_str = str(user.id)
    result = await db.execute(select(StorageBucket))
    all_buckets = result.scalars().all()
    shared = []
    for b in all_buckets:
        tags = json.loads(b.tags) if b.tags else {}
        shares = json.loads(tags.get("__shares", "{}"))
        if user_id_str in shares:
            shared.append(
                {
                    "id": str(b.id),
                    "name": b.name,
                    "owner_id": str(b.owner_id),
                    "permission": shares[user_id_str],
                }
            )
    return shared


# --- Helpers ---


async def _get_user_bucket(db: AsyncSession, user_id: uuid.UUID, bucket_id: str) -> StorageBucket:
    # Try UUID lookup first, fall back to name-based lookup
    try:
        bid = uuid.UUID(bucket_id)
        result = await db.execute(
            select(StorageBucket).where(StorageBucket.id == bid, StorageBucket.owner_id == user_id)
        )
    except ValueError:
        result = await db.execute(
            select(StorageBucket).where(StorageBucket.name == bucket_id, StorageBucket.owner_id == user_id)
        )
    bucket = result.scalar_one_or_none()
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")
    return bucket


async def _get_storage_quota(db: AsyncSession, user_id: uuid.UUID) -> dict:
    result = await db.execute(select(UserQuota).where(UserQuota.user_id == user_id))
    quota = result.scalar_one_or_none()
    return {
        "max_buckets": quota.max_buckets if quota else 5,
        "max_storage_gb": quota.max_storage_gb if quota else 50,
    }

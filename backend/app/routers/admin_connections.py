"""Admin CRUD endpoints for cluster connections (PVE, PBS, S3).

Secrets are encrypted at rest via AES-256-GCM and masked in list responses.
"""

from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.core.encryption import decrypt, encrypt, mask_secret
from app.models.models import ClusterConnection, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/connections", tags=["admin-connections"])


# --- Schemas ---


class ConnectionCreate(BaseModel):
    name: str
    conn_type: str  # pve, pbs, s3
    host: str
    port: int = 8006
    token_id: str | None = None
    token_secret: str | None = None
    password: str | None = None
    console_user: str | None = None
    console_password: str | None = None
    fingerprint: str | None = None
    verify_ssl: bool = False
    is_active: bool = True
    extra_config: dict[str, Any] | None = None


class ConnectionUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    token_id: str | None = None
    token_secret: str | None = None
    password: str | None = None
    console_user: str | None = None
    console_password: str | None = None
    fingerprint: str | None = None
    verify_ssl: bool | None = None
    is_active: bool | None = None
    extra_config: dict[str, Any] | None = None


class ConnectionRead(BaseModel):
    id: str
    name: str
    conn_type: str
    host: str
    port: int
    token_id: str | None
    token_secret_masked: str | None
    password_set: bool
    console_user: str | None
    console_password_set: bool
    fingerprint: str | None
    verify_ssl: bool
    is_active: bool
    extra_config: dict[str, Any] | None
    created_at: str
    updated_at: str


def _to_read(c: ClusterConnection) -> ConnectionRead:
    secret_masked = None
    if c.token_secret_enc:
        try:
            secret_masked = mask_secret(decrypt(c.token_secret_enc))
        except Exception:
            secret_masked = "****"
    extra = None
    if c.extra_config:
        try:
            extra = json.loads(c.extra_config)
        except Exception:
            extra = None
    return ConnectionRead(
        id=str(c.id),
        name=c.name,
        conn_type=c.conn_type,
        host=c.host,
        port=c.port,
        token_id=c.token_id,
        token_secret_masked=secret_masked,
        password_set=c.password_enc is not None,
        console_user=c.console_user,
        console_password_set=c.console_password_enc is not None,
        fingerprint=c.fingerprint,
        verify_ssl=c.verify_ssl,
        is_active=c.is_active,
        extra_config=extra,
        created_at=str(c.created_at),
        updated_at=str(c.updated_at),
    )


# --- Endpoints ---


@router.get("/", response_model=list[ConnectionRead])
async def list_connections(
    conn_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all cluster connections (secrets masked)."""
    query = select(ClusterConnection).order_by(ClusterConnection.name)
    if conn_type:
        query = query.where(ClusterConnection.conn_type == conn_type)
    result = await db.execute(query)
    return [_to_read(c) for c in result.scalars().all()]


@router.post("/", response_model=ConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Create a new cluster connection."""
    existing = await db.execute(select(ClusterConnection).where(ClusterConnection.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Connection name already exists")

    conn = ClusterConnection(
        name=body.name,
        conn_type=body.conn_type,
        host=body.host,
        port=body.port,
        token_id=body.token_id,
        token_secret_enc=encrypt(body.token_secret) if body.token_secret else None,
        password_enc=encrypt(body.password) if body.password else None,
        console_user=body.console_user,
        console_password_enc=encrypt(body.console_password) if body.console_password else None,
        fingerprint=body.fingerprint,
        verify_ssl=body.verify_ssl,
        is_active=body.is_active,
        extra_config=json.dumps(body.extra_config) if body.extra_config else None,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    # Trigger cluster registry reload
    from app.services.cluster_registry import cluster_registry

    cluster_registry.invalidate()

    logger.info("Created %s connection '%s' -> %s:%d", body.conn_type, body.name, body.host, body.port)
    return _to_read(conn)


@router.get("/{connection_id}", response_model=ConnectionRead)
async def get_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Get a specific connection by ID."""
    result = await db.execute(select(ClusterConnection).where(ClusterConnection.id == _uuid.UUID(connection_id)))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return _to_read(conn)


@router.patch("/{connection_id}", response_model=ConnectionRead)
async def update_connection(
    connection_id: str,
    body: ConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Update a cluster connection. Only provided fields are changed."""
    result = await db.execute(select(ClusterConnection).where(ClusterConnection.id == _uuid.UUID(connection_id)))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    if body.name is not None:
        conn.name = body.name
    if body.host is not None:
        conn.host = body.host
    if body.port is not None:
        conn.port = body.port
    if body.token_id is not None:
        conn.token_id = body.token_id
    if body.token_secret is not None:
        conn.token_secret_enc = encrypt(body.token_secret)
    if body.password is not None:
        conn.password_enc = encrypt(body.password)
    if body.console_user is not None:
        conn.console_user = body.console_user
    if body.console_password is not None:
        conn.console_password_enc = encrypt(body.console_password)
    if body.fingerprint is not None:
        conn.fingerprint = body.fingerprint
    if body.verify_ssl is not None:
        conn.verify_ssl = body.verify_ssl
    if body.is_active is not None:
        conn.is_active = body.is_active
    if body.extra_config is not None:
        conn.extra_config = json.dumps(body.extra_config)

    await db.commit()
    await db.refresh(conn)

    from app.services.cluster_registry import cluster_registry

    cluster_registry.invalidate()

    logger.info("Updated connection '%s'", conn.name)
    return _to_read(conn)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Delete a cluster connection."""
    result = await db.execute(select(ClusterConnection).where(ClusterConnection.id == _uuid.UUID(connection_id)))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    await db.delete(conn)
    await db.commit()

    from app.services.cluster_registry import cluster_registry

    cluster_registry.invalidate()

    logger.info("Deleted connection '%s'", conn.name)


@router.post("/{connection_id}/test")
async def test_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Test connectivity to a cluster connection."""
    result = await db.execute(select(ClusterConnection).where(ClusterConnection.id == _uuid.UUID(connection_id)))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    token_secret = decrypt(conn.token_secret_enc) if conn.token_secret_enc else ""
    password = decrypt(conn.password_enc) if conn.password_enc else ""

    if conn.conn_type == "pve":
        try:
            from app.services.proxmox_client import ProxmoxClient

            pve = ProxmoxClient(
                host=conn.host,
                port=conn.port,
                token_id=conn.token_id or "",
                token_secret=token_secret,
                verify_ssl=conn.verify_ssl,
                password=password,
                cluster_name=conn.name,
            )
            nodes = pve.get_nodes()
            return {
                "success": True,
                "message": f"Connected to {len(nodes)} node(s)",
                "nodes": [n.get("node", "") for n in nodes],
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    elif conn.conn_type == "pbs":
        try:
            from app.services.pbs_client import PBSClient

            extra = json.loads(conn.extra_config) if conn.extra_config else {}
            pbs = PBSClient(
                host=conn.host,
                port=conn.port,
                token_id=conn.token_id or "",
                token_secret=token_secret,
                fingerprint=conn.fingerprint or "",
                datastore=extra.get("datastore", "backups"),
                verify_ssl=conn.verify_ssl,
                cluster_name=conn.name,
            )
            datastores = await pbs.list_datastores()
            return {
                "success": True,
                "message": f"Connected, {len(datastores)} datastore(s)",
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    elif conn.conn_type == "s3":
        try:
            import boto3
            from botocore.config import Config as BotoConfig

            extra = json.loads(conn.extra_config) if conn.extra_config else {}
            client = boto3.client(
                "s3",
                endpoint_url=f"{'https' if conn.verify_ssl else 'http'}://{conn.host}:{conn.port}",
                aws_access_key_id=conn.token_id,
                aws_secret_access_key=token_secret,
                region_name=extra.get("region", "us-east-1"),
                config=BotoConfig(signature_version="s3v4"),
            )
            buckets = client.list_buckets()
            return {
                "success": True,
                "message": f"Connected, {len(buckets.get('Buckets', []))} bucket(s)",
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    return {"success": False, "message": f"Unknown connection type: {conn.conn_type}"}

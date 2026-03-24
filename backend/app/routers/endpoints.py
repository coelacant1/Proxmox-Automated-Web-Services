"""Service endpoint management - expose VM/container ports via reverse proxy."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import Resource, ServiceEndpoint, User
from app.services.audit_service import log_action

router = APIRouter(prefix="/api/endpoints", tags=["endpoints"])

SUBDOMAIN_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")
RESERVED_SUBDOMAINS = {"api", "app", "admin", "www", "mail", "ftp", "ssh", "ns", "dns", "paws"}
MAX_ENDPOINTS_PER_USER = 20


class EndpointCreateRequest(BaseModel):
    resource_id: str
    name: str
    protocol: str = "http"
    internal_port: int
    subdomain: str
    tls_enabled: bool = True
    auth_required: bool = False

    @field_validator("subdomain")
    @classmethod
    def validate_subdomain(cls, v: str) -> str:
        v = v.lower().strip()
        if not SUBDOMAIN_PATTERN.match(v):
            raise ValueError("Subdomain must be lowercase alphanumeric with hyphens, 1-63 chars")
        if v in RESERVED_SUBDOMAINS:
            raise ValueError(f"Subdomain '{v}' is reserved")
        return v

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        if v not in ("http", "https", "tcp", "rdp", "ssh"):
            raise ValueError("Protocol must be http, https, tcp, rdp, or ssh")
        return v

    @field_validator("internal_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("Port must be 1-65535")
        return v


class EndpointUpdateRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    tls_enabled: bool | None = None
    auth_required: bool | None = None


@router.get("")
async def list_endpoints(
    resource_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    query = select(ServiceEndpoint).where(ServiceEndpoint.owner_id == user.id)
    if resource_id:
        query = query.where(ServiceEndpoint.resource_id == uuid.UUID(resource_id))
    query = query.order_by(ServiceEndpoint.created_at.desc())

    result = await db.execute(query)
    endpoints = result.scalars().all()
    return [_serialize_endpoint(e) for e in endpoints]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    body: EndpointCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    # Quota check
    count_result = await db.execute(select(func.count(ServiceEndpoint.id)).where(ServiceEndpoint.owner_id == user.id))
    if (count_result.scalar() or 0) >= MAX_ENDPOINTS_PER_USER:
        raise HTTPException(status_code=403, detail=f"Endpoint quota exceeded ({MAX_ENDPOINTS_PER_USER} max)")

    # Verify resource ownership
    res_result = await db.execute(
        select(Resource).where(
            Resource.id == uuid.UUID(body.resource_id),
            Resource.owner_id == user.id,
            Resource.status != "destroyed",
        )
    )
    resource = res_result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    # Check subdomain uniqueness
    existing = await db.execute(select(ServiceEndpoint).where(ServiceEndpoint.subdomain == body.subdomain))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Subdomain '{body.subdomain}' is already in use")

    endpoint = ServiceEndpoint(
        resource_id=resource.id,
        owner_id=user.id,
        name=body.name,
        protocol=body.protocol,
        internal_port=body.internal_port,
        subdomain=body.subdomain,
        tls_enabled=body.tls_enabled,
        auth_required=body.auth_required,
    )
    db.add(endpoint)
    await db.commit()
    await log_action(db, user.id, "endpoint_create", resource.resource_type, resource.id)

    return _serialize_endpoint(endpoint)


# --- Ingress Settings (must be before /{endpoint_id} catch-all) ---


@router.get("/ingress-config")
async def get_ingress_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    """Get current ingress/proxy configuration (from system settings)."""
    from app.models.models import SystemSetting

    result = await db.execute(select(SystemSetting).where(SystemSetting.key.like("ingress_%")))
    settings_list = result.scalars().all()
    config = {s.key.replace("ingress_", ""): s.value for s in settings_list}
    return config


@router.get("/quota")
async def get_endpoint_quota(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get endpoint quota usage for current user."""
    count_result = await db.execute(select(func.count(ServiceEndpoint.id)).where(ServiceEndpoint.owner_id == user.id))
    used = count_result.scalar() or 0
    # Count by protocol
    proto_result = await db.execute(
        select(ServiceEndpoint.protocol, func.count(ServiceEndpoint.id))
        .where(ServiceEndpoint.owner_id == user.id)
        .group_by(ServiceEndpoint.protocol)
    )
    by_protocol = {row[0]: row[1] for row in proto_result.all()}
    return {
        "max_endpoints": MAX_ENDPOINTS_PER_USER,
        "used": used,
        "remaining": max(0, MAX_ENDPOINTS_PER_USER - used),
        "by_protocol": by_protocol,
    }


@router.get("/validate-subdomain/{subdomain}")
async def validate_subdomain_endpoint(
    subdomain: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Validate a subdomain for availability and format."""
    errors = []
    if not SUBDOMAIN_PATTERN.match(subdomain):
        errors.append("Invalid format: lowercase alphanumeric and hyphens only")
    if subdomain in RESERVED_SUBDOMAINS:
        errors.append(f"'{subdomain}' is a reserved subdomain")

    # Check collision
    existing = await db.execute(select(ServiceEndpoint).where(ServiceEndpoint.subdomain == subdomain))
    if existing.scalar_one_or_none():
        errors.append("Subdomain already in use")

    # Suggest alternatives if taken
    suggestions = []
    if errors:
        base = subdomain.rstrip("0123456789-")
        for suffix in [f"-{user.username[:8]}", "-2", "-app", "-svc"]:
            candidate = f"{base}{suffix}"
            if SUBDOMAIN_PATTERN.match(candidate) and candidate not in RESERVED_SUBDOMAINS:
                res = await db.execute(select(ServiceEndpoint).where(ServiceEndpoint.subdomain == candidate))
                if not res.scalar_one_or_none():
                    suggestions.append(candidate)
                    if len(suggestions) >= 3:
                        break

    return {"subdomain": subdomain, "valid": len(errors) == 0, "errors": errors, "suggestions": suggestions}


@router.get("/{endpoint_id}")
async def get_endpoint(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    endpoint = await _get_user_endpoint(db, user.id, endpoint_id)
    return _serialize_endpoint(endpoint)


@router.patch("/{endpoint_id}")
async def update_endpoint(
    endpoint_id: str,
    body: EndpointUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    endpoint = await _get_user_endpoint(db, user.id, endpoint_id)

    if body.name is not None:
        endpoint.name = body.name
    if body.is_active is not None:
        endpoint.is_active = body.is_active
    if body.tls_enabled is not None:
        endpoint.tls_enabled = body.tls_enabled
    if body.auth_required is not None:
        endpoint.auth_required = body.auth_required

    await db.commit()
    return {"status": "updated"}


@router.delete("/{endpoint_id}")
async def delete_endpoint(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    endpoint = await _get_user_endpoint(db, user.id, endpoint_id)
    await db.delete(endpoint)
    await db.commit()
    await log_action(db, user.id, "endpoint_delete", "endpoint", endpoint.id)
    return {"status": "deleted"}


@router.get("/{endpoint_id}/connection-info")
async def endpoint_connection_info(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    endpoint = await _get_user_endpoint(db, user.id, endpoint_id)
    fqdn = f"{endpoint.subdomain}.{endpoint.domain_suffix}"
    scheme = "https" if endpoint.tls_enabled else "http"

    info = {
        "fqdn": fqdn,
        "url": f"{scheme}://{fqdn}",
        "protocol": endpoint.protocol,
        "internal_port": endpoint.internal_port,
        "is_active": endpoint.is_active,
    }
    if endpoint.protocol == "tcp":
        info["connection_string"] = f"{fqdn}:{endpoint.internal_port}"
    elif endpoint.protocol == "rdp":
        info["connection_string"] = f"{fqdn}:{endpoint.internal_port}"
        info["rdp_file"] = f"full address:s:{fqdn}:{endpoint.internal_port}"
    elif endpoint.protocol == "ssh":
        info["connection_string"] = f"ssh -p {endpoint.internal_port} user@{fqdn}"
    return info


# --- Helpers ---


def _serialize_endpoint(e: ServiceEndpoint) -> dict:
    fqdn = f"{e.subdomain}.{e.domain_suffix}"
    return {
        "id": str(e.id),
        "resource_id": str(e.resource_id),
        "name": e.name,
        "protocol": e.protocol,
        "internal_port": e.internal_port,
        "subdomain": e.subdomain,
        "fqdn": fqdn,
        "is_active": e.is_active,
        "tls_enabled": e.tls_enabled,
        "auth_required": e.auth_required,
        "created_at": str(e.created_at),
    }


async def _get_user_endpoint(db: AsyncSession, user_id: uuid.UUID, endpoint_id: str) -> ServiceEndpoint:
    result = await db.execute(
        select(ServiceEndpoint).where(ServiceEndpoint.id == uuid.UUID(endpoint_id), ServiceEndpoint.owner_id == user_id)
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return endpoint

"""Security group management - named firewall rule sets."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import Resource, ResourceSecurityGroup, SecurityGroup, SecurityGroupRule, User
from app.schemas.schemas import SecurityGroupCreate, SecurityGroupRead, SecurityGroupRuleCreate, SecurityGroupRuleRead
from app.services.cluster_registry import NoClustersConfigured, cluster_registry

router = APIRouter(prefix="/api/security-groups", tags=["security-groups"])

# Pre-built security group templates
SG_TEMPLATES = {
    "web-server": {
        "name": "Web Server",
        "description": "HTTP/HTTPS inbound access",
        "rules": [
            {"direction": "ingress", "protocol": "tcp", "port_from": 80, "port_to": 80, "cidr": "0.0.0.0/0"},
            {"direction": "ingress", "protocol": "tcp", "port_from": 443, "port_to": 443, "cidr": "0.0.0.0/0"},
        ],
    },
    "ssh-only": {
        "name": "SSH Only",
        "description": "SSH inbound access",
        "rules": [
            {"direction": "ingress", "protocol": "tcp", "port_from": 22, "port_to": 22, "cidr": "0.0.0.0/0"},
        ],
    },
    "database": {
        "name": "Database",
        "description": "Common database ports (MySQL, PostgreSQL, Redis)",
        "rules": [
            {"direction": "ingress", "protocol": "tcp", "port_from": 3306, "port_to": 3306, "cidr": "10.0.0.0/8"},
            {"direction": "ingress", "protocol": "tcp", "port_from": 5432, "port_to": 5432, "cidr": "10.0.0.0/8"},
            {"direction": "ingress", "protocol": "tcp", "port_from": 6379, "port_to": 6379, "cidr": "10.0.0.0/8"},
        ],
    },
    "allow-all": {
        "name": "Allow All",
        "description": "Unrestricted inbound/outbound (use with caution)",
        "rules": [
            {"direction": "ingress", "protocol": "tcp", "port_from": 1, "port_to": 65535, "cidr": "0.0.0.0/0"},
            {"direction": "ingress", "protocol": "udp", "port_from": 1, "port_to": 65535, "cidr": "0.0.0.0/0"},
            {"direction": "ingress", "protocol": "icmp", "port_from": 0, "port_to": 0, "cidr": "0.0.0.0/0"},
        ],
    },
    "rdp": {
        "name": "Remote Desktop",
        "description": "RDP inbound access",
        "rules": [
            {"direction": "ingress", "protocol": "tcp", "port_from": 3389, "port_to": 3389, "cidr": "0.0.0.0/0"},
        ],
    },
}


@router.get("/", response_model=list[SecurityGroupRead])
async def list_security_groups(
    resource_id: str | None = None,
    cluster_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    if resource_id:
        # List SGs attached to a specific resource
        query = (
            select(SecurityGroup)
            .join(ResourceSecurityGroup)
            .where(
                ResourceSecurityGroup.resource_id == uuid.UUID(resource_id),
                SecurityGroup.owner_id == user.id,
            )
            .options(selectinload(SecurityGroup.rules))
        )
        result = await db.execute(query)
    else:
        query = (
            select(SecurityGroup)
            .where(SecurityGroup.owner_id == user.id)
            .options(selectinload(SecurityGroup.rules))
            .order_by(SecurityGroup.created_at.desc())
        )
        result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/", response_model=SecurityGroupRead, status_code=status.HTTP_201_CREATED)
async def create_security_group(
    body: SecurityGroupCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    try:
        _cluster_id = cluster_registry.default_cluster
    except NoClustersConfigured:
        raise HTTPException(
            status_code=503, detail="No Proxmox cluster configured. Add one via Admin > Infrastructure."
        )

    existing = await db.execute(
        select(SecurityGroup).where(
            SecurityGroup.owner_id == user.id,
            SecurityGroup.name == body.name,
            SecurityGroup.cluster_id == _cluster_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Security group name already exists")

    sg = SecurityGroup(owner_id=user.id, name=body.name, description=body.description, cluster_id=_cluster_id)
    db.add(sg)
    await db.commit()

    # Re-fetch with rules
    result = await db.execute(
        select(SecurityGroup).where(SecurityGroup.id == sg.id).options(selectinload(SecurityGroup.rules))
    )
    return result.scalar_one()


# --- Templates (must be before /{sg_id} to avoid path conflict) ---


@router.get("/templates")
async def list_templates():
    """List available security group templates."""
    return {
        k: {"name": v["name"], "description": v["description"], "rule_count": len(v["rules"])}
        for k, v in SG_TEMPLATES.items()
    }


class FromTemplateRequest(BaseModel):
    cluster_id: str = "default"


@router.post("/from-template/{template_id}", response_model=SecurityGroupRead, status_code=status.HTTP_201_CREATED)
async def create_from_template(
    template_id: str,
    body: FromTemplateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Create a security group from a pre-built template."""
    if template_id not in SG_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    try:
        cluster_id = cluster_registry.default_cluster
    except NoClustersConfigured:
        raise HTTPException(
            status_code=503, detail="No Proxmox cluster configured. Add one via Admin > Infrastructure."
        )
    tpl = SG_TEMPLATES[template_id]

    existing = await db.execute(
        select(SecurityGroup).where(
            SecurityGroup.owner_id == user.id,
            SecurityGroup.name == tpl["name"],
            SecurityGroup.cluster_id == cluster_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Security group '{tpl['name']}' already exists")

    sg = SecurityGroup(owner_id=user.id, name=tpl["name"], description=tpl["description"], cluster_id=cluster_id)
    db.add(sg)
    await db.flush()

    for rule_data in tpl["rules"]:
        rule = SecurityGroupRule(security_group_id=sg.id, **rule_data)
        db.add(rule)

    await db.commit()

    result = await db.execute(
        select(SecurityGroup).where(SecurityGroup.id == sg.id).options(selectinload(SecurityGroup.rules))
    )
    return result.scalar_one()


# --- Individual SG operations ---


@router.get("/{sg_id}", response_model=SecurityGroupRead)
async def get_security_group(
    sg_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    sg = await _get_user_sg(db, user.id, sg_id)
    # Reload with rules
    await db.refresh(sg, ["rules"])
    return sg


@router.delete("/{sg_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_security_group(
    sg_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    sg = await _get_user_sg(db, user.id, sg_id, min_perm="admin")
    await db.execute(delete(ResourceSecurityGroup).where(ResourceSecurityGroup.security_group_id == sg.id))
    await db.delete(sg)
    await db.commit()


# --- Rules ---


@router.post("/{sg_id}/rules", response_model=SecurityGroupRuleRead, status_code=status.HTTP_201_CREATED)
async def add_rule(
    sg_id: str,
    body: SecurityGroupRuleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    sg = await _get_user_sg(db, user.id, sg_id, min_perm="admin")

    if body.direction not in ("ingress", "egress"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Direction must be ingress/egress")
    if body.protocol not in ("tcp", "udp", "icmp"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Protocol must be tcp/udp/icmp")

    rule = SecurityGroupRule(security_group_id=sg.id, **body.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/{sg_id}/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    sg_id: str,
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await _get_user_sg(db, user.id, sg_id, min_perm="admin")

    rule_result = await db.execute(
        select(SecurityGroupRule).where(SecurityGroupRule.id == rule_id, SecurityGroupRule.security_group_id == sg_id)
    )
    rule = rule_result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    await db.delete(rule)
    await db.commit()


# --- Resource Association ---


class SGAttachRequest(BaseModel):
    resource_id: str


@router.post("/{sg_id}/attach", status_code=status.HTTP_201_CREATED)
async def attach_security_group(
    sg_id: str,
    body: SGAttachRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Attach a security group to a resource (VM/container)."""
    sg = await _get_user_sg(db, user.id, sg_id)
    resource = await _get_user_resource(db, user.id, body.resource_id)

    # Check if already attached
    existing = await db.execute(
        select(ResourceSecurityGroup).where(
            ResourceSecurityGroup.resource_id == resource.id,
            ResourceSecurityGroup.security_group_id == sg.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Security group already attached to this resource")

    link = ResourceSecurityGroup(resource_id=resource.id, security_group_id=sg.id)
    db.add(link)
    await db.commit()
    return {"status": "attached", "resource_id": str(resource.id), "security_group_id": str(sg.id)}


@router.post("/{sg_id}/detach")
async def detach_security_group(
    sg_id: str,
    body: SGAttachRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Detach a security group from a resource."""
    sg = await _get_user_sg(db, user.id, sg_id)

    result = await db.execute(
        select(ResourceSecurityGroup).where(
            ResourceSecurityGroup.resource_id == uuid.UUID(body.resource_id),
            ResourceSecurityGroup.security_group_id == sg.id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Security group not attached to this resource")

    await db.delete(link)
    await db.commit()
    return {"status": "detached"}


@router.get("/{sg_id}/resources")
async def list_attached_resources(
    sg_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List resources attached to a security group."""
    sg = await _get_user_sg(db, user.id, sg_id)

    result = await db.execute(
        select(Resource)
        .join(ResourceSecurityGroup)
        .where(
            ResourceSecurityGroup.security_group_id == sg.id,
            Resource.owner_id == user.id,
        )
    )
    resources = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "name": r.display_name,
            "type": r.resource_type,
            "status": r.status,
        }
        for r in resources
    ]


# --- Helpers ---


async def _get_user_sg(
    db: AsyncSession,
    user_id: uuid.UUID,
    sg_id: str,
    min_perm: str = "read",
) -> SecurityGroup:
    sid = uuid.UUID(sg_id) if isinstance(sg_id, str) else sg_id
    result = await db.execute(select(SecurityGroup).where(SecurityGroup.id == sid, SecurityGroup.owner_id == user_id))
    sg = result.scalar_one_or_none()
    if not sg:
        from app.services.group_access import check_group_access

        res2 = await db.execute(select(SecurityGroup).where(SecurityGroup.id == sid))
        sg = res2.scalar_one_or_none()
        if sg and not await check_group_access(db, user_id, "security_group", sid, min_perm):
            sg = None
    if not sg:
        raise HTTPException(status_code=404, detail="Security group not found")
    return sg


async def _get_user_resource(db: AsyncSession, user_id: uuid.UUID, resource_id: str) -> Resource:
    result = await db.execute(
        select(Resource).where(
            Resource.id == uuid.UUID(resource_id),
            Resource.owner_id == user_id,
            Resource.status != "destroyed",
        )
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource

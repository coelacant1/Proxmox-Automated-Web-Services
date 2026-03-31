"""User groups for IAM-style resource sharing."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_capability
from app.models.models import (
    VPC,
    Alarm,
    Backup,
    DNSRecord,
    GroupAPIKey,
    GroupResourceShare,
    GroupRole,
    Resource,
    SecurityGroup,
    ServiceEndpoint,
    SSHKeyPair,
    StorageBucket,
    User,
    UserGroup,
    UserGroupMember,
    Volume,
)

router = APIRouter(prefix="/api/groups", tags=["groups"])

VALID_PERMISSIONS = ["read", "operate", "admin"]
ROLE_HIERARCHY = {GroupRole.OWNER: 0, GroupRole.ADMIN: 1, GroupRole.MEMBER: 2, GroupRole.VIEWER: 3}

# All shareable entity types with their model, owner column, and display name field
ENTITY_TYPES: dict[str, dict[str, Any]] = {
    "resource": {"model": Resource, "owner": "owner_id", "name": "display_name", "label": "Instance"},
    "vpc": {"model": VPC, "owner": "owner_id", "name": "name", "label": "VPC"},
    "volume": {"model": Volume, "owner": "owner_id", "name": "name", "label": "Volume"},
    "bucket": {"model": StorageBucket, "owner": "owner_id", "name": "name", "label": "Bucket"},
    "endpoint": {"model": ServiceEndpoint, "owner": "owner_id", "name": "name", "label": "Endpoint"},
    "ssh_key": {"model": SSHKeyPair, "owner": "owner_id", "name": "name", "label": "SSH Key"},
    "security_group": {"model": SecurityGroup, "owner": "owner_id", "name": "name", "label": "Security Group"},
    "dns_record": {"model": DNSRecord, "owner": "owner_id", "name": "name", "label": "DNS Record"},
    "backup": {"model": Backup, "owner": "owner_id", "name": "notes", "label": "Backup"},
    "alarm": {"model": Alarm, "owner": "owner_id", "name": "name", "label": "Alarm"},
}


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class MemberAdd(BaseModel):
    username: str
    role: str = "member"


class ShareResource(BaseModel):
    entity_type: str = "resource"
    entity_id: uuid.UUID
    permission: str = "read"


def _group_dict(g: UserGroup, members: list | None = None) -> dict:
    d = {
        "id": str(g.id),
        "name": g.name,
        "description": g.description,
        "owner_id": str(g.owner_id),
        "owner_username": g.owner.username if g.owner else None,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "member_count": len(g.members) if g.members else 0,
    }
    if members is not None:
        d["members"] = members
    return d


async def _get_group_with_access(
    group_id: uuid.UUID, user: User, db: AsyncSession, min_role: str = GroupRole.VIEWER
) -> tuple[UserGroup, UserGroupMember | None]:
    """Fetch group and verify user access. Returns (group, membership)."""
    result = await db.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(404, "Group not found")

    # Owner always has full access
    if group.owner_id == user.id:
        return group, None

    # Admin users always have access
    if user.role == "admin" or user.is_superuser:
        return group, None

    result = await db.execute(
        select(UserGroupMember).where(
            UserGroupMember.group_id == group_id,
            UserGroupMember.user_id == user.id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(403, "Not a member of this group")

    if ROLE_HIERARCHY.get(membership.role, 99) > ROLE_HIERARCHY.get(min_role, 99):
        raise HTTPException(403, "Insufficient group role")

    return group, membership


# --- Group CRUD ---


@router.post("/", status_code=201)
async def create_group(
    body: GroupCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_capability("group.create")),
):
    group = UserGroup(name=body.name, description=body.description, owner_id=user.id)
    db.add(group)
    await db.flush()

    # Add owner as member with OWNER role
    member = UserGroupMember(group_id=group.id, user_id=user.id, role=GroupRole.OWNER)
    db.add(member)
    await db.commit()
    await db.refresh(group)
    return _group_dict(group)


@router.get("/")
async def list_groups(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    # Groups where user is owner or member
    member_result = await db.execute(select(UserGroupMember.group_id).where(UserGroupMember.user_id == user.id))
    group_ids = [r[0] for r in member_result.all()]
    if not group_ids:
        return []

    result = await db.execute(select(UserGroup).where(UserGroup.id.in_(group_ids)))
    return [_group_dict(g) for g in result.scalars().all()]


@router.get("/entity-types")
async def list_entity_types(_: User = Depends(get_current_active_user)):
    """List all shareable entity types."""
    return [{"type": k, "label": v["label"]} for k, v in ENTITY_TYPES.items()]


@router.get("/my-entities")
async def list_my_entities(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List all entities the current user owns, grouped by type."""
    result: dict[str, list[dict]] = {}
    for etype, cfg in ENTITY_TYPES.items():
        model = cfg["model"]
        owner_col = getattr(model, cfg["owner"])
        q = select(model).where(owner_col == user.id)
        rows = await db.execute(q)
        items = []
        for entity in rows.scalars().all():
            name = getattr(entity, cfg["name"], None) or f"{cfg['label']} {str(entity.id)[:8]}"
            items.append({"id": str(entity.id), "name": str(name), "type": etype, "label": cfg["label"]})
        if items:
            result[etype] = items
    return result


@router.get("/shared-with-me", name="shared_with_me")
async def shared_with_me(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """All entities shared to the current user through any group."""
    member_result = await db.execute(select(UserGroupMember.group_id).where(UserGroupMember.user_id == user.id))
    group_ids = [r[0] for r in member_result.all()]
    if not group_ids:
        return []

    result = await db.execute(select(GroupResourceShare).where(GroupResourceShare.group_id.in_(group_ids)))
    shares = result.scalars().all()

    perm_order = {"admin": 0, "operate": 1, "read": 2}
    by_entity: dict[str, dict] = {}
    for s in shares:
        key = f"{s.entity_type}:{s.entity_id}"
        if key not in by_entity or perm_order.get(s.permission, 99) < perm_order.get(by_entity[key]["permission"], 99):
            cfg = ENTITY_TYPES.get(s.entity_type, {})
            by_entity[key] = {
                "entity_type": s.entity_type,
                "entity_id": str(s.entity_id),
                "entity_label": cfg.get("label", s.entity_type),
                "permission": s.permission,
                "group_id": str(s.group_id),
            }

    for item in by_entity.values():
        cfg = ENTITY_TYPES.get(item["entity_type"])
        if cfg:
            entity = await db.get(cfg["model"], uuid.UUID(item["entity_id"]))
            if entity:
                item["entity_name"] = str(
                    getattr(entity, cfg["name"], None) or f"{cfg['label']} {item['entity_id'][:8]}"
                )
            else:
                item["entity_name"] = "(deleted)"
        else:
            item["entity_name"] = item["entity_id"][:8]

    return list(by_entity.values())


@router.get("/{group_id}")
async def get_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    group, membership = await _get_group_with_access(group_id, user, db)

    my_role = "viewer"
    if group.owner_id == user.id:
        my_role = GroupRole.OWNER
    elif user.role == "admin" or user.is_superuser:
        my_role = GroupRole.ADMIN
    elif membership:
        my_role = membership.role

    members = []
    for m in group.members:
        members.append(
            {
                "id": str(m.id),
                "user_id": str(m.user_id),
                "username": m.user.username if m.user else None,
                "email": m.user.email if m.user else None,
                "role": m.role,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            }
        )

    result = _group_dict(group, members=members)
    result["my_role"] = my_role
    return result


@router.patch("/{group_id}")
async def update_group(
    group_id: uuid.UUID,
    body: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    group, _ = await _get_group_with_access(group_id, user, db, min_role=GroupRole.ADMIN)
    if body.name is not None:
        group.name = body.name
    if body.description is not None:
        group.description = body.description
    await db.commit()
    await db.refresh(group)
    return _group_dict(group)


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(404, "Group not found")
    if group.owner_id != user.id and user.role != "admin" and not user.is_superuser:
        raise HTTPException(403, "Only the group owner can delete this group")
    await db.delete(group)
    await db.commit()


# --- Member management ---


@router.post("/{group_id}/members")
async def add_member(
    group_id: uuid.UUID,
    body: MemberAdd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_capability("group.manage")),
):
    await _get_group_with_access(group_id, user, db, min_role=GroupRole.ADMIN)

    # Find user by username
    result = await db.execute(select(User).where(User.username == body.username))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")

    # Check not already a member
    existing = await db.execute(
        select(UserGroupMember).where(
            UserGroupMember.group_id == group_id,
            UserGroupMember.user_id == target.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "User is already a member")

    if body.role not in [GroupRole.ADMIN, GroupRole.MEMBER, GroupRole.VIEWER]:
        raise HTTPException(400, "Invalid role")

    member = UserGroupMember(group_id=group_id, user_id=target.id, role=body.role)
    db.add(member)
    await db.commit()
    return {"user_id": str(target.id), "username": target.username, "role": body.role}


@router.patch("/{group_id}/members/{user_id}")
async def update_member_role(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    group, _ = await _get_group_with_access(group_id, user, db, min_role=GroupRole.ADMIN)

    if role not in [GroupRole.ADMIN, GroupRole.MEMBER, GroupRole.VIEWER]:
        raise HTTPException(400, "Invalid role")

    result = await db.execute(
        select(UserGroupMember).where(
            UserGroupMember.group_id == group_id,
            UserGroupMember.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(404, "Member not found")

    if membership.role == GroupRole.OWNER:
        raise HTTPException(400, "Cannot change owner role")

    membership.role = role
    await db.commit()
    return {"user_id": str(user_id), "role": role}


@router.delete("/{group_id}/members/{user_id}", status_code=204)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    group, _ = await _get_group_with_access(group_id, user, db, min_role=GroupRole.ADMIN)

    result = await db.execute(
        select(UserGroupMember).where(
            UserGroupMember.group_id == group_id,
            UserGroupMember.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(404, "Member not found")
    if membership.role == GroupRole.OWNER:
        raise HTTPException(400, "Cannot remove the group owner")

    await db.delete(membership)
    await db.commit()


# --- Resource sharing ---


async def _resolve_entity(db: AsyncSession, entity_type: str, entity_id: uuid.UUID) -> tuple[Any, str]:
    """Resolve an entity by type/id. Returns (entity, display_name)."""
    cfg = ENTITY_TYPES.get(entity_type)
    if not cfg:
        raise HTTPException(400, f"Unknown entity type: {entity_type}. Valid: {list(ENTITY_TYPES.keys())}")
    model = cfg["model"]
    entity = await db.get(model, entity_id)
    if not entity:
        raise HTTPException(404, f"{cfg['label']} not found")
    name_field = cfg["name"]
    display = getattr(entity, name_field, None) or f"{cfg['label']} {str(entity_id)[:8]}"
    return entity, str(display)


@router.post("/{group_id}/share")
async def share_resource(
    group_id: uuid.UUID,
    body: ShareResource,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_capability("resource.share")),
):
    await _get_group_with_access(group_id, user, db, min_role=GroupRole.MEMBER)

    if body.permission not in VALID_PERMISSIONS:
        raise HTTPException(400, f"permission must be one of {VALID_PERMISSIONS}")

    # Resolve and verify ownership
    entity, _ = await _resolve_entity(db, body.entity_type, body.entity_id)
    cfg = ENTITY_TYPES[body.entity_type]
    owner_id = getattr(entity, cfg["owner"])
    if owner_id != user.id and user.role != "admin" and not user.is_superuser:
        raise HTTPException(403, "You can only share entities you own")

    # Check not already shared
    existing = await db.execute(
        select(GroupResourceShare).where(
            GroupResourceShare.group_id == group_id,
            GroupResourceShare.entity_type == body.entity_type,
            GroupResourceShare.entity_id == body.entity_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Already shared with this group")

    share = GroupResourceShare(
        group_id=group_id,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        resource_id=body.entity_id if body.entity_type == "resource" else None,
        permission=body.permission,
        shared_by=user.id,
    )
    db.add(share)
    await db.commit()
    return {"entity_type": body.entity_type, "entity_id": str(body.entity_id), "permission": body.permission}


@router.delete("/{group_id}/share/{share_id}", status_code=204)
async def unshare_resource(
    group_id: uuid.UUID,
    share_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await _get_group_with_access(group_id, user, db, min_role=GroupRole.MEMBER)

    result = await db.execute(
        select(GroupResourceShare).where(
            GroupResourceShare.group_id == group_id,
            GroupResourceShare.id == share_id,
        )
    )
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(404, "Share not found")

    # Only the person who shared or group admin/owner can unshare
    if share.shared_by != user.id:
        await _get_group_with_access(group_id, user, db, min_role=GroupRole.ADMIN)

    await db.delete(share)
    await db.commit()


@router.get("/{group_id}/resources")
async def list_shared_resources(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await _get_group_with_access(group_id, user, db)

    result = await db.execute(select(GroupResourceShare).where(GroupResourceShare.group_id == group_id))
    shares = result.scalars().all()
    out = []
    for s in shares:
        name = None
        cfg = ENTITY_TYPES.get(s.entity_type)
        if cfg:
            entity = await db.get(cfg["model"], s.entity_id)
            if entity:
                name = str(getattr(entity, cfg["name"], None) or f"{cfg['label']} {str(s.entity_id)[:8]}")
        out.append(
            {
                "id": str(s.id),
                "entity_type": s.entity_type,
                "entity_id": str(s.entity_id),
                "entity_name": name,
                "entity_label": cfg["label"] if cfg else s.entity_type,
                "permission": s.permission,
                "shared_by": str(s.shared_by),
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )
    return out


# --- Detailed entity data for group dashboard ---

# Define which fields to serialize for each entity type
_ENTITY_DETAIL_FIELDS: dict[str, list[str]] = {
    "resource": ["resource_type", "status", "proxmox_vmid", "proxmox_node", "specs", "tags"],
    "vpc": ["cidr", "gateway", "status", "dhcp_enabled", "is_default"],
    "volume": ["size_gib", "storage_pool", "status", "disk_slot", "proxmox_node"],
    "bucket": ["region", "size_bytes", "object_count", "versioning_enabled", "is_public"],
    "endpoint": ["protocol", "internal_port", "subdomain", "domain_suffix", "is_active", "tls_enabled"],
    "ssh_key": ["fingerprint"],
    "security_group": ["description"],
    "dns_record": ["record_type", "value", "ttl"],
    "backup": ["backup_type", "status", "size_bytes", "proxmox_storage", "started_at", "completed_at"],
    "alarm": ["metric", "comparison", "threshold", "state", "is_active"],
}


def _serialize_field(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return str(val)
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


@router.get("/{group_id}/dashboard")
async def group_dashboard(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Return all shared entities with full details, grouped by type."""
    await _get_group_with_access(group_id, user, db)

    result = await db.execute(select(GroupResourceShare).where(GroupResourceShare.group_id == group_id))
    shares = result.scalars().all()

    by_type: dict[str, list[dict]] = {}
    for s in shares:
        cfg = ENTITY_TYPES.get(s.entity_type)
        if not cfg:
            continue
        entity = await db.get(cfg["model"], s.entity_id)
        name_field = cfg["name"]
        name = (
            str(getattr(entity, name_field, None) or f"{cfg['label']} {str(s.entity_id)[:8]}")
            if entity
            else "(deleted)"
        )

        item: dict[str, Any] = {
            "share_id": str(s.id),
            "entity_id": str(s.entity_id),
            "entity_name": name,
            "permission": s.permission,
            "shared_by": str(s.shared_by),
        }

        if entity:
            for field in _ENTITY_DETAIL_FIELDS.get(s.entity_type, []):
                item[field] = _serialize_field(getattr(entity, field, None))

        by_type.setdefault(s.entity_type, []).append(item)

    return {
        "types": {
            etype: {"label": cfg["label"], "items": by_type.get(etype, [])}
            for etype, cfg in ENTITY_TYPES.items()
            if etype in by_type
        }
    }


# --- Group API Tokens ----------------------------------------------------


class GroupTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class GroupTokenRead(BaseModel):
    id: str
    name: str
    key_prefix: str
    is_active: bool
    created_by_username: str
    created_at: str
    last_used_at: str | None

    model_config = {"from_attributes": True}


class GroupTokenCreated(GroupTokenRead):
    raw_key: str


@router.get("/{group_id}/tokens", response_model=list[GroupTokenRead])
async def list_group_tokens(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List API tokens for a group. Must be group admin or owner."""
    member = await _get_group_with_access(group_id, user, db, min_role=GroupRole.ADMIN)  # noqa: F841
    result = await db.execute(
        select(GroupAPIKey).where(GroupAPIKey.group_id == group_id).order_by(GroupAPIKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        GroupTokenRead(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            is_active=k.is_active,
            created_by_username=k.creator.username if k.creator else "unknown",
            created_at=str(k.created_at),
            last_used_at=str(k.last_used_at) if k.last_used_at else None,
        )
        for k in keys
    ]


@router.post("/{group_id}/tokens", response_model=GroupTokenCreated, status_code=201)
async def create_group_token(
    group_id: uuid.UUID,
    body: GroupTokenCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Create a group-scoped API token. Must be group admin or owner."""
    member = await _get_group_with_access(group_id, user, db, min_role=GroupRole.ADMIN)  # noqa: F841
    from app.services.api_key_service import create_group_api_key

    key_record, raw_key = await create_group_api_key(db, group_id, user.id, body.name)
    return GroupTokenCreated(
        id=str(key_record.id),
        name=key_record.name,
        key_prefix=key_record.key_prefix,
        is_active=key_record.is_active,
        created_by_username=user.username,
        created_at=str(key_record.created_at),
        last_used_at=None,
        raw_key=raw_key,
    )


@router.delete("/{group_id}/tokens/{token_id}", status_code=204)
async def revoke_group_token(
    group_id: uuid.UUID,
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Revoke a group API token. Must be group admin or owner."""
    member = await _get_group_with_access(group_id, user, db, min_role=GroupRole.ADMIN)  # noqa: F841
    result = await db.execute(select(GroupAPIKey).where(GroupAPIKey.id == token_id, GroupAPIKey.group_id == group_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="Token not found")
    key.is_active = False
    await db.commit()

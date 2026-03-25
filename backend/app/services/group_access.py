"""Utilities for checking group-level access to shared entities."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    GroupResourceShare,
    UserGroup,
    UserGroupMember,
)

PERM_LEVEL = {"read": 0, "operate": 1, "admin": 2}


async def get_group_permission(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
) -> str | None:
    """Return the highest permission a user has on an entity via any group share.

    Group admins/owners automatically get 'admin' permission on all shared
    resources regardless of the share's permission field.

    Returns 'read', 'operate', 'admin', or None if no group access.
    """
    # Find all group shares for this entity where the user is a member or owner
    result = await db.execute(
        select(GroupResourceShare.permission, UserGroupMember.role)
        .join(
            UserGroupMember,
            UserGroupMember.group_id == GroupResourceShare.group_id,
        )
        .where(
            GroupResourceShare.entity_type == entity_type,
            GroupResourceShare.entity_id == entity_id,
            or_(
                UserGroupMember.user_id == user_id,
                GroupResourceShare.group_id.in_(select(UserGroup.id).where(UserGroup.owner_id == user_id)),
            ),
        )
    )
    rows = result.all()
    if not rows:
        return None

    # Group admins/owners get full admin access on shared resources
    for share_perm, member_role in rows:
        if member_role == "admin":
            return "admin"

    perms = [r[0] for r in rows]
    return max(perms, key=lambda p: PERM_LEVEL.get(p, -1))


async def check_group_access(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    min_permission: str = "read",
) -> bool:
    """Check if a user has at least min_permission on an entity via group shares."""
    perm = await get_group_permission(db, user_id, entity_type, entity_id)
    if perm is None:
        return False
    return PERM_LEVEL.get(perm, -1) >= PERM_LEVEL.get(min_permission, 0)

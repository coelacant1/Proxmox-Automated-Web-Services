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

    Returns 'read', 'operate', 'admin', or None if no group access.
    """
    result = await db.execute(
        select(GroupResourceShare.permission)
        .join(
            UserGroupMember,
            UserGroupMember.group_id == GroupResourceShare.group_id,
        )
        .where(
            GroupResourceShare.entity_type == entity_type,
            GroupResourceShare.entity_id == entity_id,
            or_(
                UserGroupMember.user_id == user_id,
                # Also check if user is the group owner
                GroupResourceShare.group_id.in_(select(UserGroup.id).where(UserGroup.owner_id == user_id)),
            ),
        )
    )
    perms = [r[0] for r in result.all()]
    if not perms:
        return None
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

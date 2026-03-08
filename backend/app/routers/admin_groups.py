"""Admin endpoints for system-wide group management."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.models import (
    AuditLog,
    GroupResourceShare,
    User,
    UserGroup,
    UserGroupMember,
)

router = APIRouter(prefix="/api/admin/groups", tags=["admin-groups"])


@router.get("/")
async def list_all_groups(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    search: str = Query("", max_length=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all groups in the system with member/share counts."""
    base = select(UserGroup).options(selectinload(UserGroup.owner))
    if search:
        base = base.where(UserGroup.name.ilike(f"%{search}%"))
    base = base.order_by(UserGroup.created_at.desc())

    total_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(total_q)).scalar() or 0

    result = await db.execute(base.offset((page - 1) * per_page).limit(per_page))
    groups = list(result.scalars().all())

    items = []
    for g in groups:
        member_count = (
            await db.execute(
                select(func.count()).where(UserGroupMember.group_id == g.id)
            )
        ).scalar() or 0
        share_count = (
            await db.execute(
                select(func.count()).where(GroupResourceShare.group_id == g.id)
            )
        ).scalar() or 0
        items.append(
            {
                "id": str(g.id),
                "name": g.name,
                "description": g.description,
                "owner": {
                    "id": str(g.owner.id),
                    "username": g.owner.username,
                    "email": g.owner.email,
                },
                "member_count": member_count,
                "share_count": share_count,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
        )

    return {"items": items, "total": total, "page": page, "pages": (total + per_page - 1) // per_page}


@router.get("/{group_id}")
async def get_group_detail(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Get full group detail for admin view."""
    result = await db.execute(
        select(UserGroup)
        .where(UserGroup.id == group_id)
        .options(
            selectinload(UserGroup.owner),
            selectinload(UserGroup.members).selectinload(UserGroupMember.user),
            selectinload(UserGroup.shared_resources),
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    members = []
    for m in group.members:
        members.append(
            {
                "user_id": str(m.user_id),
                "username": m.user.username if m.user else "Unknown",
                "email": m.user.email if m.user else None,
                "role": m.role,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            }
        )

    shares = []
    for s in group.shared_resources:
        shares.append(
            {
                "id": str(s.id),
                "entity_type": s.entity_type,
                "entity_id": str(s.entity_id),
                "permission": s.permission,
                "shared_by": str(s.shared_by),
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )

    return {
        "id": str(group.id),
        "name": group.name,
        "description": group.description,
        "owner": {
            "id": str(group.owner.id),
            "username": group.owner.username,
            "email": group.owner.email,
        },
        "members": members,
        "shared_resources": shares,
        "created_at": group.created_at.isoformat() if group.created_at else None,
    }


@router.get("/{group_id}/audit")
async def get_group_audit(
    group_id: uuid.UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Get audit log entries related to a group."""
    result = await db.execute(select(UserGroup).where(UserGroup.id == group_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Group not found")

    base = (
        select(AuditLog)
        .where(AuditLog.resource_type == "group", AuditLog.resource_id == str(group_id))
        .order_by(AuditLog.created_at.desc())
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    result = await db.execute(base.offset((page - 1) * per_page).limit(per_page))
    items = [
        {
            "id": str(a.id),
            "action": a.action,
            "user_id": str(a.user_id) if a.user_id else None,
            "details": a.details,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in result.scalars().all()
    ]
    return {"items": items, "total": total, "page": page, "pages": (total + per_page - 1) // per_page}


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Admin force-delete a group."""
    result = await db.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    await db.delete(group)
    await db.commit()

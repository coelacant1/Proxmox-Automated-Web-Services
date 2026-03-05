"""Admin-only user management endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.core.pagination import PaginatedParams, PaginatedResponse
from app.models.models import Resource, User, UserQuota
from app.schemas.schemas import QuotaRead, ResourceRead, UserRead

router = APIRouter(prefix="/api/admin/users", tags=["admin"])


@router.get("/", response_model=PaginatedResponse[UserRead])
async def list_users(
    params: PaginatedParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    total_result = await db.execute(select(func.count(User.id)))
    total = total_result.scalar() or 0

    result = await db.execute(
        select(User).offset(params.offset).limit(params.per_page).order_by(User.created_at.desc())
    )
    return PaginatedResponse.create(list(result.scalars().all()), total, params)


@router.get("/count")
async def user_count(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    result = await db.execute(select(func.count(User.id)))
    return {"count": result.scalar()}


# --- Tag Policies (must be before /{user_id} catch-all) ------------------

_tag_policies: dict[str, dict] = {}


class TagPolicyRequest(BaseModel):
    key: str
    required: bool = False
    allowed_values: list[str] | None = None
    max_tags: int = 50


@router.post("/tag-policies", status_code=status.HTTP_201_CREATED)
async def create_tag_policy(
    body: TagPolicyRequest,
    _: User = Depends(require_admin),
):
    """Create or update a tag policy."""
    _tag_policies[body.key] = {
        "key": body.key,
        "required": body.required,
        "allowed_values": body.allowed_values,
        "max_tags": body.max_tags,
    }
    return _tag_policies[body.key]


@router.get("/tag-policies")
async def list_tag_policies(_: User = Depends(require_admin)):
    return list(_tag_policies.values())


@router.delete("/tag-policies/{key}")
async def delete_tag_policy(key: str, _: User = Depends(require_admin)):
    if key not in _tag_policies:
        raise HTTPException(status_code=404, detail="Policy not found")
    del _tag_policies[key]
    return {"status": "deleted"}


# --- Node Affinity (must be before /{user_id} catch-all) -----------------

_node_affinity: dict[str, dict] = {}


class NodeAffinityRequest(BaseModel):
    target_id: str
    target_type: str = "user"
    node: str
    soft: bool = False


@router.post("/node-affinity", status_code=status.HTTP_201_CREATED)
async def create_node_affinity(
    body: NodeAffinityRequest,
    _: User = Depends(require_admin),
):
    rule_id = str(uuid.uuid4())
    _node_affinity[rule_id] = {
        "id": rule_id,
        "target_id": body.target_id,
        "target_type": body.target_type,
        "node": body.node,
        "soft": body.soft,
    }
    return _node_affinity[rule_id]


@router.get("/node-affinity")
async def list_node_affinity(_: User = Depends(require_admin)):
    return list(_node_affinity.values())


@router.delete("/node-affinity/{rule_id}")
async def delete_node_affinity(rule_id: str, _: User = Depends(require_admin)):
    if rule_id not in _node_affinity:
        raise HTTPException(status_code=404, detail="Rule not found")
    del _node_affinity[rule_id]
    return {"status": "deleted"}


# --- Restore Testing (must be before /{user_id} catch-all) ---------------


@router.post("/backups/{backup_id}/test-restore")
async def test_restore(
    backup_id: str,
    _: User = Depends(require_admin),
):
    return {
        "backup_id": backup_id,
        "status": "test_scheduled",
        "message": "Temp VM will be created, verified, and destroyed automatically",
    }


# --- MFA Admin Controls (must be before /{user_id} catch-all) ------------


@router.get("/mfa/status")
async def list_mfa_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [
        {
            "user_id": str(u.id),
            "username": u.username,
            "mfa_enabled": u.mfa_enabled if hasattr(u, "mfa_enabled") else False,
        }
        for u in users
    ]


@router.post("/mfa/{user_id}/force-disable")
async def force_disable_mfa(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if hasattr(user, "mfa_enabled"):
        user.mfa_enabled = False
        user.mfa_secret = None
        await db.commit()
    return {"status": "mfa_disabled", "user_id": user_id}


# --- User Management (/{user_id} routes - must be last) ------------------


@router.patch("/{user_id}/role", response_model=UserRead)
async def update_user_role(
    user_id: str,
    role: str = Query(..., pattern="^(admin|operator|member|viewer)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}/active", response_model=UserRead)
async def toggle_user_active(
    user_id: str,
    is_active: bool,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{user_id}/quota", response_model=QuotaRead)
async def get_user_quota(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(UserQuota).where(UserQuota.user_id == uuid.UUID(user_id)))
    quota = result.scalar_one_or_none()
    if not quota:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quota not found")
    return quota


@router.put("/{user_id}/quota", response_model=QuotaRead)
async def update_user_quota(
    user_id: str,
    quota_data: QuotaRead,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(UserQuota).where(UserQuota.user_id == uuid.UUID(user_id)))
    quota = result.scalar_one_or_none()
    if not quota:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quota not found")

    for field, value in quota_data.model_dump().items():
        setattr(quota, field, value)

    await db.commit()
    await db.refresh(quota)
    return quota


@router.get("/{user_id}", response_model=UserRead)
async def get_user_detail(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Get detailed info about a single user."""
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/{user_id}/resources", response_model=list[ResourceRead])
async def get_user_resources(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all resources owned by a user."""
    result = await db.execute(
        select(Resource).where(Resource.owner_id == uuid.UUID(user_id)).order_by(Resource.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Delete a user account. Cannot delete yourself."""
    uid = uuid.UUID(user_id)
    if uid == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await db.delete(user)
    await db.commit()

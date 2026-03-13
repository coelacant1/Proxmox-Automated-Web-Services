"""Admin CRUD for user tiers (capability bundles)."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import TierRequest, User, UserTier

router = APIRouter(prefix="/api/admin/tiers", tags=["admin-tiers"])

# All known capabilities
ALL_CAPABILITIES = [
    "template.request",
    "ha.manage",
    "group.create",
    "group.manage",
    "volume.share",
    "vpc.share",
    "resource.share",
    "bucket.share",
]


class TierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    capabilities: list[str] = []
    is_default: bool = False
    idle_shutdown_days: int | None = None
    idle_destroy_days: int | None = None
    account_inactive_days: int | None = None
    max_subnet_prefix: int | None = None


class TierUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    capabilities: list[str] | None = None
    is_default: bool | None = None
    idle_shutdown_days: int | None = Field(None)
    idle_destroy_days: int | None = Field(None)
    account_inactive_days: int | None = Field(None)
    max_subnet_prefix: int | None = Field(None)


def _tier_dict(t: UserTier) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "description": t.description,
        "capabilities": json.loads(t.capabilities),
        "is_default": t.is_default,
        "idle_shutdown_days": t.idle_shutdown_days,
        "idle_destroy_days": t.idle_destroy_days,
        "account_inactive_days": t.account_inactive_days,
        "max_subnet_prefix": t.max_subnet_prefix,
        "bandwidth_limit_mbps": t.bandwidth_limit_mbps,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/capabilities")
async def list_capabilities(_: User = Depends(require_admin)):
    """List all available capability strings."""
    return ALL_CAPABILITIES


@router.get("/")
async def list_tiers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(UserTier).order_by(UserTier.name))
    tiers = result.scalars().all()
    return [_tier_dict(t) for t in tiers]


@router.post("/", status_code=201)
async def create_tier(
    body: TierCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    # Validate capabilities
    invalid = [c for c in body.capabilities if c not in ALL_CAPABILITIES]
    if invalid:
        raise HTTPException(400, f"Unknown capabilities: {invalid}")

    # If setting as default, unset any existing default
    if body.is_default:
        await db.execute(update(UserTier).values(is_default=False))

    tier = UserTier(
        name=body.name,
        description=body.description,
        capabilities=json.dumps(body.capabilities),
        is_default=body.is_default,
        idle_shutdown_days=body.idle_shutdown_days,
        idle_destroy_days=body.idle_destroy_days,
        account_inactive_days=body.account_inactive_days,
        max_subnet_prefix=body.max_subnet_prefix,
    )
    db.add(tier)
    await db.commit()
    await db.refresh(tier)
    return _tier_dict(tier)


@router.patch("/{tier_id}")
async def update_tier(
    tier_id: uuid.UUID,
    body: TierUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(UserTier).where(UserTier.id == tier_id))
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(404, "Tier not found")

    if body.name is not None:
        tier.name = body.name
    if body.description is not None:
        tier.description = body.description
    if body.capabilities is not None:
        invalid = [c for c in body.capabilities if c not in ALL_CAPABILITIES]
        if invalid:
            raise HTTPException(400, f"Unknown capabilities: {invalid}")
        tier.capabilities = json.dumps(body.capabilities)
    if body.is_default is not None:
        if body.is_default:
            await db.execute(update(UserTier).values(is_default=False))
        tier.is_default = body.is_default
    if body.idle_shutdown_days is not None:
        tier.idle_shutdown_days = body.idle_shutdown_days if body.idle_shutdown_days >= 0 else None
    if body.idle_destroy_days is not None:
        tier.idle_destroy_days = body.idle_destroy_days if body.idle_destroy_days >= 0 else None
    if body.account_inactive_days is not None:
        tier.account_inactive_days = body.account_inactive_days if body.account_inactive_days >= 0 else None
    if body.max_subnet_prefix is not None:
        tier.max_subnet_prefix = body.max_subnet_prefix if body.max_subnet_prefix > 0 else None

    await db.commit()
    await db.refresh(tier)
    return _tier_dict(tier)


@router.delete("/{tier_id}", status_code=204)
async def delete_tier(
    tier_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(UserTier).where(UserTier.id == tier_id))
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(404, "Tier not found")

    # Unassign users from this tier
    await db.execute(update(User).where(User.tier_id == tier_id).values(tier_id=None))
    await db.delete(tier)
    await db.commit()


@router.patch("/users/{user_id}/tier")
async def assign_user_tier(
    user_id: uuid.UUID,
    tier_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Assign a tier to a user, or pass tier_id=null to remove."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    if tier_id:
        tier_result = await db.execute(select(UserTier).where(UserTier.id == tier_id))
        if not tier_result.scalar_one_or_none():
            raise HTTPException(404, "Tier not found")

    user.tier_id = tier_id
    await db.commit()
    return {"user_id": str(user_id), "tier_id": str(tier_id) if tier_id else None}


# --- Admin: Tier request review ---

@router.get("/requests")
async def list_tier_requests(
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = select(TierRequest).order_by(TierRequest.created_at.desc())
    if status_filter:
        q = q.where(TierRequest.status == status_filter)
    result = await db.execute(q)
    return [_request_dict(r) for r in result.scalars().all()]


@router.patch("/requests/{request_id}")
async def review_tier_request(
    request_id: uuid.UUID,
    body: ReviewBody,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(TierRequest).where(TierRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, "Request already reviewed")

    req.status = body.status
    req.admin_notes = body.admin_notes
    req.reviewed_by = admin.id

    # If approved, assign the tier to the user
    if body.status == "approved":
        user_result = await db.execute(select(User).where(User.id == req.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.tier_id = req.tier_id

    await db.commit()
    await db.refresh(req)
    return _request_dict(req)


class ReviewBody(BaseModel):
    status: str  # approved or rejected
    admin_notes: str | None = None


def _request_dict(r: TierRequest) -> dict:
    return {
        "id": str(r.id),
        "user_id": str(r.user_id),
        "username": r.user.username if r.user else None,
        "email": r.user.email if r.user else None,
        "tier_id": str(r.tier_id),
        "tier_name": r.tier.name if r.tier else None,
        "reason": r.reason,
        "status": r.status,
        "admin_notes": r.admin_notes,
        "reviewed_by": r.reviewer.username if r.reviewer else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# --- User-facing tier endpoints (separate prefix) ---

user_router = APIRouter(prefix="/api/tiers", tags=["tiers"])


@user_router.get("/")
async def list_available_tiers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    """List all tiers visible to users."""
    result = await db.execute(select(UserTier).order_by(UserTier.name))
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "description": t.description,
            "capabilities": json.loads(t.capabilities),
            "is_default": t.is_default,
            "idle_shutdown_days": t.idle_shutdown_days,
            "idle_destroy_days": t.idle_destroy_days,
            "account_inactive_days": t.account_inactive_days,
            "max_subnet_prefix": t.max_subnet_prefix,
            "bandwidth_limit_mbps": t.bandwidth_limit_mbps,
        }
        for t in result.scalars().all()
    ]


@user_router.get("/me")
async def get_my_tier(user: User = Depends(get_current_active_user)):
    """Get the current user's assigned tier."""
    if user.tier:
        return {
            "id": str(user.tier.id),
            "name": user.tier.name,
            "description": user.tier.description,
            "capabilities": json.loads(user.tier.capabilities),
            "idle_shutdown_days": user.tier.idle_shutdown_days,
            "idle_destroy_days": user.tier.idle_destroy_days,
            "account_inactive_days": user.tier.account_inactive_days,
            "max_subnet_prefix": user.tier.max_subnet_prefix,
            "bandwidth_limit_mbps": user.tier.bandwidth_limit_mbps,
        }
    return None


@user_router.post("/request", status_code=201)
async def request_tier(
    body: TierRequestBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Submit a request to be assigned a specific tier."""
    # Verify tier exists
    tier = await db.get(UserTier, body.tier_id)
    if not tier:
        raise HTTPException(404, "Tier not found")

    # Already on this tier?
    if user.tier_id and str(user.tier_id) == str(body.tier_id):
        raise HTTPException(400, "You are already on this tier")

    # Check for existing pending request
    existing = await db.execute(
        select(TierRequest).where(
            TierRequest.user_id == user.id,
            TierRequest.status == "pending",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "You already have a pending tier request")

    req = TierRequest(user_id=user.id, tier_id=body.tier_id, reason=body.reason)
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return _request_dict(req)


@user_router.get("/requests/mine")
async def my_tier_requests(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List the current user's tier requests."""
    result = await db.execute(
        select(TierRequest)
        .where(TierRequest.user_id == user.id)
        .order_by(TierRequest.created_at.desc())
    )
    return [_request_dict(r) for r in result.scalars().all()]


class TierRequestBody(BaseModel):
    tier_id: uuid.UUID
    reason: str | None = None

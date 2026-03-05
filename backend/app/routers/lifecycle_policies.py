"""Lifecycle policy API - automated instance actions (auto-stop, TTL, schedules)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import LifecyclePolicy, Resource, User
from app.services.audit_service import log_action

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])

VALID_POLICY_TYPES = {"auto_stop", "auto_start", "ttl", "schedule"}
VALID_ACTIONS = {"stop", "start", "terminate", "hibernate"}
MAX_POLICIES_PER_USER = 50


class PolicyCreateRequest(BaseModel):
    resource_id: str
    policy_type: str
    action: str
    cron_expression: str | None = None
    expires_at: str | None = None

    @field_validator("policy_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_POLICY_TYPES:
            raise ValueError(f"Type must be one of: {', '.join(VALID_POLICY_TYPES)}")
        return v

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in VALID_ACTIONS:
            raise ValueError(f"Action must be one of: {', '.join(VALID_ACTIONS)}")
        return v


class PolicyUpdateRequest(BaseModel):
    cron_expression: str | None = None
    is_active: bool | None = None


@router.get("/policies")
async def list_policies(
    resource_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    query = select(LifecyclePolicy).where(LifecyclePolicy.owner_id == user.id)
    if resource_id:
        query = query.where(LifecyclePolicy.resource_id == uuid.UUID(resource_id))
    query = query.order_by(LifecyclePolicy.created_at.desc())

    result = await db.execute(query)
    policies = result.scalars().all()
    return [_serialize(p) for p in policies]


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def create_policy(
    body: PolicyCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    # Quota
    count = await db.execute(
        select(func.count(LifecyclePolicy.id)).where(LifecyclePolicy.owner_id == user.id)
    )
    if (count.scalar() or 0) >= MAX_POLICIES_PER_USER:
        raise HTTPException(status_code=403, detail="Lifecycle policy quota exceeded")

    # Verify resource
    resource = await db.execute(
        select(Resource).where(
            Resource.id == uuid.UUID(body.resource_id),
            Resource.owner_id == user.id,
            Resource.status != "destroyed",
        )
    )
    if not resource.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Resource not found")

    policy = LifecyclePolicy(
        owner_id=user.id,
        resource_id=uuid.UUID(body.resource_id),
        policy_type=body.policy_type,
        action=body.action,
        cron_expression=body.cron_expression,
    )
    db.add(policy)
    await db.commit()
    await log_action(db, user.id, "lifecycle_policy_create", "policy", policy.id)

    return _serialize(policy)


@router.get("/policies/{policy_id}")
async def get_policy(
    policy_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    policy = await _get_user_policy(db, user.id, policy_id)
    return _serialize(policy)


@router.patch("/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    body: PolicyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    policy = await _get_user_policy(db, user.id, policy_id)
    if body.cron_expression is not None:
        policy.cron_expression = body.cron_expression
    if body.is_active is not None:
        policy.is_active = body.is_active
    await db.commit()
    return {"status": "updated"}


@router.delete("/policies/{policy_id}")
async def delete_policy(
    policy_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    policy = await _get_user_policy(db, user.id, policy_id)
    await db.delete(policy)
    await db.commit()
    return {"status": "deleted"}


# --- Helpers ---


def _serialize(p: LifecyclePolicy) -> dict:
    return {
        "id": str(p.id),
        "resource_id": str(p.resource_id),
        "policy_type": p.policy_type,
        "action": p.action,
        "cron_expression": p.cron_expression,
        "is_active": p.is_active,
        "expires_at": str(p.expires_at) if p.expires_at else None,
        "created_at": str(p.created_at),
    }


async def _get_user_policy(db: AsyncSession, user_id: uuid.UUID, policy_id: str) -> LifecyclePolicy:
    result = await db.execute(
        select(LifecyclePolicy).where(
            LifecyclePolicy.id == uuid.UUID(policy_id),
            LifecyclePolicy.owner_id == user_id,
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy

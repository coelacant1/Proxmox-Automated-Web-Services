"""System rules/restrictions - admin CRUD and user read endpoint."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import SystemRule, User

router = APIRouter(prefix="/api", tags=["system-rules"])

VALID_CATEGORIES = ["General", "Compute", "Storage", "Network", "Security", "Other"]
VALID_SEVERITIES = ["info", "warning", "restriction"]


class RuleCreate(BaseModel):
    category: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    severity: str = "info"
    sort_order: int = 0
    is_active: bool = True


class RuleUpdate(BaseModel):
    category: str | None = None
    title: str | None = None
    description: str | None = None
    severity: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class ReorderItem(BaseModel):
    id: uuid.UUID
    sort_order: int


def _rule_to_dict(r: SystemRule) -> dict:
    return {
        "id": str(r.id),
        "category": r.category,
        "title": r.title,
        "description": r.description,
        "severity": r.severity,
        "sort_order": r.sort_order,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# --- User endpoint (active rules only) ---


@router.get("/system/rules")
async def list_active_rules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(SystemRule).where(SystemRule.is_active.is_(True)).order_by(SystemRule.category, SystemRule.sort_order)
    )
    return [_rule_to_dict(r) for r in result.scalars().all()]


# --- Admin endpoints ---


@router.get("/admin/rules")
async def admin_list_rules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(SystemRule).order_by(SystemRule.category, SystemRule.sort_order))
    return [_rule_to_dict(r) for r in result.scalars().all()]


@router.post("/admin/rules", status_code=201)
async def create_rule(
    body: RuleCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    if body.severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"severity must be one of {VALID_SEVERITIES}")
    rule = SystemRule(
        category=body.category,
        title=body.title,
        description=body.description,
        severity=body.severity,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_to_dict(rule)


@router.patch("/admin/rules/{rule_id}")
async def update_rule(
    rule_id: uuid.UUID,
    body: RuleUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(SystemRule).where(SystemRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Rule not found")

    if body.category is not None:
        rule.category = body.category
    if body.title is not None:
        rule.title = body.title
    if body.description is not None:
        rule.description = body.description
    if body.severity is not None:
        if body.severity not in VALID_SEVERITIES:
            raise HTTPException(400, f"severity must be one of {VALID_SEVERITIES}")
        rule.severity = body.severity
    if body.sort_order is not None:
        rule.sort_order = body.sort_order
    if body.is_active is not None:
        rule.is_active = body.is_active

    await db.commit()
    await db.refresh(rule)
    return _rule_to_dict(rule)


@router.delete("/admin/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(SystemRule).where(SystemRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Rule not found")
    await db.delete(rule)
    await db.commit()


@router.patch("/admin/rules/reorder")
async def reorder_rules(
    items: list[ReorderItem],
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    for item in items:
        await db.execute(update(SystemRule).where(SystemRule.id == item.id).values(sort_order=item.sort_order))
    await db.commit()
    return {"updated": len(items)}

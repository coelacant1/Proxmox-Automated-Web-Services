"""Cost tracking and billing API.

Provides cost rate management (admin) and user billing estimates
based on active resource usage.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import CostRate, Resource, User

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _parse_specs(raw) -> dict:
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, dict):
        return raw
    return {}


DEFAULT_RATES = {
    ("vm", "cpu_hour"): 0.01,
    ("vm", "ram_gb_hour"): 0.005,
    ("vm", "disk_gb_month"): 0.10,
    ("lxc", "cpu_hour"): 0.005,
    ("lxc", "ram_gb_hour"): 0.003,
    ("lxc", "disk_gb_month"): 0.08,
    ("bucket", "storage_gb_month"): 0.023,
    ("bucket", "request_1k"): 0.004,
    ("volume", "gb_month"): 0.10,
}


class CostRateRequest(BaseModel):
    resource_type: str
    metric: str
    rate: float
    currency: str = "USD"


# --- Admin: Manage Rates ---


@router.get("/rates")
async def list_cost_rates(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_active_user),
):
    """List all cost rates."""
    result = await db.execute(
        select(CostRate).where(CostRate.is_active.is_(True)).order_by(CostRate.resource_type)
    )
    rates = result.scalars().all()
    if not rates:
        return [
            {
                "resource_type": rt,
                "metric": m,
                "rate": r,
                "currency": "USD",
                "source": "default",
            }
            for (rt, m), r in DEFAULT_RATES.items()
        ]
    return [
        {
            "id": str(r.id),
            "resource_type": r.resource_type,
            "metric": r.metric,
            "rate": r.rate,
            "currency": r.currency,
            "source": "custom",
        }
        for r in rates
    ]


@router.put("/rates")
async def set_cost_rate(
    body: CostRateRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Set or update a cost rate (admin only)."""
    result = await db.execute(
        select(CostRate).where(
            CostRate.resource_type == body.resource_type,
            CostRate.metric == body.metric,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.rate = body.rate
        existing.currency = body.currency
    else:
        rate = CostRate(
            resource_type=body.resource_type,
            metric=body.metric,
            rate=body.rate,
            currency=body.currency,
        )
        db.add(rate)

    await db.commit()
    return {"status": "rate_set"}


# --- User: Billing Estimate ---


@router.get("/estimate")
async def get_billing_estimate(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get estimated monthly cost for current resources."""
    result = await db.execute(
        select(Resource).where(
            Resource.owner_id == user.id,
            Resource.status.notin_(["destroyed", "terminated"]),
        )
    )
    resources = result.scalars().all()

    # Load custom rates or use defaults
    rate_result = await db.execute(select(CostRate).where(CostRate.is_active.is_(True)))
    custom_rates = {(r.resource_type, r.metric): r.rate for r in rate_result.scalars().all()}

    def get_rate(rtype: str, metric: str) -> float:
        return custom_rates.get((rtype, metric), DEFAULT_RATES.get((rtype, metric), 0))

    total = 0.0
    items = []
    for r in resources:
        specs = _parse_specs(r.specs)
        cpu = specs.get("cpu", 1)
        ram_gb = specs.get("ram_mb", 512) / 1024
        disk_gb = specs.get("disk_gb", 10)
        rtype = r.resource_type if r.resource_type in ("vm", "lxc") else "vm"

        monthly_cost = (
            cpu * get_rate(rtype, "cpu_hour") * 730
            + ram_gb * get_rate(rtype, "ram_gb_hour") * 730
            + disk_gb * get_rate(rtype, "disk_gb_month")
        )
        total += monthly_cost
        items.append({
            "resource_id": str(r.id),
            "name": r.display_name,
            "type": r.resource_type,
            "monthly_estimate": round(monthly_cost, 2),
        })

    return {
        "total_monthly_estimate": round(total, 2),
        "currency": "USD",
        "resource_count": len(items),
        "items": items,
    }


@router.get("/resources/{resource_id}")
async def get_resource_cost(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get detailed cost breakdown for a specific resource."""
    import uuid as _uuid

    result = await db.execute(
        select(Resource).where(Resource.id == _uuid.UUID(resource_id), Resource.owner_id == user.id)
    )
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    rate_result = await db.execute(select(CostRate).where(CostRate.is_active.is_(True)))
    custom_rates = {(r.resource_type, r.metric): r.rate for r in rate_result.scalars().all()}

    def get_rate(rtype: str, metric: str) -> float:
        return custom_rates.get((rtype, metric), DEFAULT_RATES.get((rtype, metric), 0))

    specs = _parse_specs(resource.specs)
    cpu = specs.get("cpu", 1)
    ram_gb = specs.get("ram_mb", 512) / 1024
    disk_gb = specs.get("disk_gb", 10)
    rtype = resource.resource_type if resource.resource_type in ("vm", "lxc") else "vm"

    breakdown = {
        "cpu": {
            "units": cpu, "rate": get_rate(rtype, "cpu_hour"),
            "monthly": round(cpu * get_rate(rtype, "cpu_hour") * 730, 2),
        },
        "ram": {
            "units_gb": round(ram_gb, 2), "rate": get_rate(rtype, "ram_gb_hour"),
            "monthly": round(ram_gb * get_rate(rtype, "ram_gb_hour") * 730, 2),
        },
        "disk": {
            "units_gb": disk_gb, "rate": get_rate(rtype, "disk_gb_month"),
            "monthly": round(disk_gb * get_rate(rtype, "disk_gb_month"), 2),
        },
    }
    total = sum(v["monthly"] for v in breakdown.values())

    return {
        "resource_id": str(resource.id),
        "name": resource.display_name,
        "type": resource.resource_type,
        "status": resource.status,
        "breakdown": breakdown,
        "total_monthly": round(total, 2),
        "currency": "USD",
    }


@router.get("/summary")
async def get_billing_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get billing summary grouped by resource type."""

    result = await db.execute(
        select(Resource).where(
            Resource.owner_id == user.id,
            Resource.status.notin_(["destroyed", "terminated"]),
        )
    )
    resources = result.scalars().all()

    by_type: dict[str, dict] = {}
    for r in resources:
        rtype = r.resource_type
        if rtype not in by_type:
            by_type[rtype] = {"count": 0, "total_monthly": 0.0}
        by_type[rtype]["count"] += 1

        specs = _parse_specs(r.specs)
        cpu = specs.get("cpu", 1)
        ram_gb = specs.get("ram_mb", 512) / 1024
        disk_gb = specs.get("disk_gb", 10)
        etype = rtype if rtype in ("vm", "lxc") else "vm"
        cost = (
            cpu * DEFAULT_RATES.get((etype, "cpu_hour"), 0) * 730
            + ram_gb * DEFAULT_RATES.get((etype, "ram_gb_hour"), 0) * 730
            + disk_gb * DEFAULT_RATES.get((etype, "disk_gb_month"), 0)
        )
        by_type[rtype]["total_monthly"] = round(by_type[rtype]["total_monthly"] + cost, 2)

    grand_total = sum(v["total_monthly"] for v in by_type.values())
    return {
        "by_type": by_type,
        "grand_total": round(grand_total, 2),
        "currency": "USD",
        "resource_count": len(resources),
    }


@router.get("/quota-status")
async def get_cost_quota_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get cost usage vs monthly credit quota with threshold warnings."""
    from app.models.models import UserQuota

    # Get user quota (monthly_credits)
    quota_result = await db.execute(select(UserQuota).where(UserQuota.user_id == user.id))
    quota = quota_result.scalar_one_or_none()
    monthly_credits = 100.0  # default
    if quota and hasattr(quota, "monthly_credits") and quota.monthly_credits is not None:
        monthly_credits = float(quota.monthly_credits)

    # Calculate current spend (reuse estimate logic)
    resources_result = await db.execute(
        select(Resource).where(Resource.owner_id == user.id, Resource.status != "terminated")
    )
    resources = resources_result.scalars().all()

    total_monthly = 0.0
    for r in resources:
        specs = _parse_specs(r)
        rtype = r.resource_type or "vm"
        etype = "vm" if rtype in ("vm", "lxc") else rtype
        cpu = specs.get("cpu", specs.get("cores", 0))
        ram_mb = specs.get("ram_mb", specs.get("memory_mb", 0))
        disk_gb = specs.get("disk_gb", 0)
        cost = (
            cpu * DEFAULT_RATES.get((etype, "cpu_core_month"), 0)
            + (ram_mb / 1024) * DEFAULT_RATES.get((etype, "ram_gb_month"), 0)
            + disk_gb * DEFAULT_RATES.get((etype, "disk_gb_month"), 0)
        )
        total_monthly += cost

    usage_pct = round((total_monthly / monthly_credits * 100) if monthly_credits > 0 else 0, 1)
    warnings = []
    if usage_pct >= 100:
        warnings.append("quota_exceeded")
    elif usage_pct >= 95:
        warnings.append("quota_critical")
    elif usage_pct >= 80:
        warnings.append("quota_warning")

    return {
        "monthly_credits": monthly_credits,
        "current_spend": round(total_monthly, 2),
        "usage_percent": usage_pct,
        "remaining": round(max(0, monthly_credits - total_monthly), 2),
        "warnings": warnings,
    }

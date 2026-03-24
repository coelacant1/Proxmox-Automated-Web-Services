"""Monitoring metrics and alarms API.

Provides per-instance metrics (CPU, memory, disk, network) from Proxmox RRD
data, and user-configurable alarms with threshold-based alerting.
"""

import secrets
import uuid
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import Alarm, CustomMetric, Resource, User
from app.services.audit_service import log_action
from app.services.proxmox_client import proxmox_client

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

VALID_METRICS = {"cpu", "memory", "disk", "netin", "netout", "diskread", "diskwrite"}
VALID_COMPARISONS = {"gt", "gte", "lt", "lte", "eq"}
VALID_TIMEFRAMES = {"hour", "day", "week", "month", "year"}
MAX_ALARMS_PER_USER = 25


# --- Schemas ---


class AlarmCreateRequest(BaseModel):
    resource_id: str
    name: str
    metric: str
    comparison: str
    threshold: float
    period_seconds: int = 300
    evaluation_periods: int = 1
    notify_email: bool = True
    notify_webhook: str | None = None

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, v: str) -> str:
        if v not in VALID_METRICS:
            raise ValueError(f"Metric must be one of: {', '.join(sorted(VALID_METRICS))}")
        return v

    @field_validator("comparison")
    @classmethod
    def validate_comparison(cls, v: str) -> str:
        if v not in VALID_COMPARISONS:
            raise ValueError(f"Comparison must be one of: {', '.join(sorted(VALID_COMPARISONS))}")
        return v

    @field_validator("period_seconds")
    @classmethod
    def validate_period(cls, v: int) -> int:
        if v < 60 or v > 86400:
            raise ValueError("Period must be 60-86400 seconds")
        return v


class AlarmUpdateRequest(BaseModel):
    name: str | None = None
    threshold: float | None = None
    period_seconds: int | None = None
    evaluation_periods: int | None = None
    notify_email: bool | None = None
    notify_webhook: str | None = None
    is_active: bool | None = None


# --- Metrics Endpoints ---


@router.get("/metrics/{resource_id}")
async def get_resource_metrics(
    resource_id: str,
    timeframe: str = "hour",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get RRD metrics for a resource from Proxmox."""
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"Timeframe must be one of: {', '.join(VALID_TIMEFRAMES)}")

    resource = await _get_resource(db, user.id, resource_id)
    vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"

    try:
        rrd_data = proxmox_client.get_rrd_data(resource.proxmox_node, resource.proxmox_vmid, vmtype, timeframe)
        return {"resource_id": resource_id, "timeframe": timeframe, "data": rrd_data}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/metrics/{resource_id}/current")
async def get_current_metrics(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get current real-time metrics for a resource."""
    resource = await _get_resource(db, user.id, resource_id)

    try:
        if resource.resource_type == "lxc":
            status_data = proxmox_client.get_container_status(resource.proxmox_node, resource.proxmox_vmid)
        else:
            status_data = proxmox_client.get_vm_status(resource.proxmox_node, resource.proxmox_vmid)

        return {
            "resource_id": resource_id,
            "status": status_data.get("status"),
            "cpu": status_data.get("cpu", 0),
            "memory": {
                "used": status_data.get("mem", 0),
                "total": status_data.get("maxmem", 0),
                "percent": round(status_data.get("mem", 0) / max(status_data.get("maxmem", 1), 1) * 100, 1),
            },
            "disk": {
                "used": status_data.get("disk", 0),
                "total": status_data.get("maxdisk", 0),
            },
            "network": {
                "in": status_data.get("netin", 0),
                "out": status_data.get("netout", 0),
            },
            "uptime": status_data.get("uptime", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Alarm Endpoints ---


@router.get("/alarms")
async def list_alarms(
    resource_id: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    query = select(Alarm).where(Alarm.owner_id == user.id)
    if resource_id:
        query = query.where(Alarm.resource_id == uuid.UUID(resource_id))
    if state:
        query = query.where(Alarm.state == state)
    query = query.order_by(Alarm.created_at.desc())

    result = await db.execute(query)
    alarms = result.scalars().all()
    return [_serialize_alarm(a) for a in alarms]


@router.post("/alarms", status_code=status.HTTP_201_CREATED)
async def create_alarm(
    body: AlarmCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    # Quota check
    count_result = await db.execute(select(func.count(Alarm.id)).where(Alarm.owner_id == user.id))
    if (count_result.scalar() or 0) >= MAX_ALARMS_PER_USER:
        raise HTTPException(status_code=403, detail=f"Alarm quota exceeded ({MAX_ALARMS_PER_USER} max)")

    # Verify resource ownership
    resource = await _get_resource(db, user.id, body.resource_id)

    alarm = Alarm(
        owner_id=user.id,
        resource_id=resource.id,
        name=body.name,
        metric=body.metric,
        comparison=body.comparison,
        threshold=body.threshold,
        period_seconds=body.period_seconds,
        evaluation_periods=body.evaluation_periods,
        notify_email=body.notify_email,
        notify_webhook=body.notify_webhook,
    )
    db.add(alarm)
    await db.commit()
    await log_action(db, user.id, "alarm_create", resource.resource_type, resource.id)

    return _serialize_alarm(alarm)


@router.get("/alarms/{alarm_id}")
async def get_alarm(
    alarm_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    alarm = await _get_user_alarm(db, user.id, alarm_id)
    return _serialize_alarm(alarm)


@router.patch("/alarms/{alarm_id}")
async def update_alarm(
    alarm_id: str,
    body: AlarmUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    alarm = await _get_user_alarm(db, user.id, alarm_id)

    fields = (
        "name",
        "threshold",
        "period_seconds",
        "evaluation_periods",
        "notify_email",
        "notify_webhook",
        "is_active",
    )
    for field in fields:
        val = getattr(body, field, None)
        if val is not None:
            setattr(alarm, field, val)

    await db.commit()
    return {"status": "updated"}


@router.delete("/alarms/{alarm_id}")
async def delete_alarm(
    alarm_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    alarm = await _get_user_alarm(db, user.id, alarm_id)
    await db.delete(alarm)
    await db.commit()
    return {"status": "deleted"}


# --- Helpers ---


def _serialize_alarm(a: Alarm) -> dict:
    return {
        "id": str(a.id),
        "resource_id": str(a.resource_id),
        "name": a.name,
        "metric": a.metric,
        "comparison": a.comparison,
        "threshold": a.threshold,
        "period_seconds": a.period_seconds,
        "evaluation_periods": a.evaluation_periods,
        "state": a.state,
        "notify_email": a.notify_email,
        "notify_webhook": a.notify_webhook,
        "is_active": a.is_active,
        "last_evaluated_at": str(a.last_evaluated_at) if a.last_evaluated_at else None,
        "last_state_change_at": str(a.last_state_change_at) if a.last_state_change_at else None,
        "created_at": str(a.created_at),
    }


async def _get_resource(db: AsyncSession, user_id: uuid.UUID, resource_id: str) -> Resource:
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


async def _get_user_alarm(db: AsyncSession, user_id: uuid.UUID, alarm_id: str) -> Alarm:
    result = await db.execute(select(Alarm).where(Alarm.id == uuid.UUID(alarm_id), Alarm.owner_id == user_id))
    alarm = result.scalar_one_or_none()
    if not alarm:
        raise HTTPException(status_code=404, detail="Alarm not found")
    return alarm


# --- Custom Metrics ---

MAX_CUSTOM_METRICS_PER_USER = 1000


class CustomMetricCreate(BaseModel):
    namespace: str
    metric_name: str
    value: float
    unit: str | None = None
    resource_id: str | None = None
    dimensions: dict[str, str] | None = None


class CustomMetricBatch(BaseModel):
    metrics: list[CustomMetricCreate]


@router.post("/custom-metrics", status_code=status.HTTP_201_CREATED)
async def push_custom_metric(
    body: CustomMetricCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Push a custom metric data point."""
    import json

    count = await db.scalar(select(func.count()).where(CustomMetric.owner_id == user.id))
    if count and count >= MAX_CUSTOM_METRICS_PER_USER:
        raise HTTPException(status_code=429, detail="Custom metric limit reached")

    metric = CustomMetric(
        owner_id=user.id,
        namespace=body.namespace,
        metric_name=body.metric_name,
        value=body.value,
        unit=body.unit,
        resource_id=uuid.UUID(body.resource_id) if body.resource_id else None,
        dimensions=json.dumps(body.dimensions) if body.dimensions else None,
    )
    db.add(metric)
    await db.commit()
    return {"status": "created", "metric_id": str(metric.id)}


@router.post("/custom-metrics/batch", status_code=status.HTTP_201_CREATED)
async def push_custom_metrics_batch(
    body: CustomMetricBatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Push multiple custom metric data points."""
    import json

    if len(body.metrics) > 25:
        raise HTTPException(status_code=400, detail="Max 25 metrics per batch")

    created = []
    for m in body.metrics:
        metric = CustomMetric(
            owner_id=user.id,
            namespace=m.namespace,
            metric_name=m.metric_name,
            value=m.value,
            unit=m.unit,
            resource_id=uuid.UUID(m.resource_id) if m.resource_id else None,
            dimensions=json.dumps(m.dimensions) if m.dimensions else None,
        )
        db.add(metric)
        created.append(metric)

    await db.commit()
    return {"status": "created", "count": len(created)}


@router.get("/custom-metrics")
async def list_custom_metrics(
    namespace: str | None = None,
    metric_name: str | None = None,
    resource_id: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Query custom metrics with filters."""
    import json

    query = select(CustomMetric).where(CustomMetric.owner_id == user.id)
    if namespace:
        query = query.where(CustomMetric.namespace == namespace)
    if metric_name:
        query = query.where(CustomMetric.metric_name == metric_name)
    if resource_id:
        query = query.where(CustomMetric.resource_id == uuid.UUID(resource_id))

    query = query.order_by(CustomMetric.timestamp.desc()).limit(min(limit, 500))
    result = await db.execute(query)
    metrics = result.scalars().all()

    return [
        {
            "id": str(m.id),
            "namespace": m.namespace,
            "metric_name": m.metric_name,
            "value": m.value,
            "unit": m.unit,
            "resource_id": str(m.resource_id) if m.resource_id else None,
            "dimensions": json.loads(m.dimensions) if m.dimensions else None,
            "timestamp": str(m.timestamp),
        }
        for m in metrics
    ]


# --- Custom Metrics API Keys ---------------------------------------------

# In-memory key storage (production: DB model)
_metrics_keys: dict[str, list[dict]] = {}  # user_id -> [{key, label, created_at}]
MAX_METRICS_KEYS = 5


@router.post("/metrics-keys", status_code=status.HTTP_201_CREATED)
async def create_metrics_key(
    label: str = "default",
    user: User = Depends(get_current_active_user),
):
    """Create an API key for pushing custom metrics."""
    user_keys = _metrics_keys.setdefault(str(user.id), [])
    if len(user_keys) >= MAX_METRICS_KEYS:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_METRICS_KEYS} metrics keys allowed")

    key = f"paws_mk_{secrets.token_hex(16)}"
    from datetime import datetime

    entry = {
        "key": key,
        "label": label,
        "created_at": str(datetime.now(UTC)),
    }
    user_keys.append(entry)
    return entry


@router.get("/metrics-keys")
async def list_metrics_keys(user: User = Depends(get_current_active_user)):
    """List user's metrics API keys."""
    user_keys = _metrics_keys.get(str(user.id), [])
    return [{"key": k["key"][:12] + "...", "label": k["label"], "created_at": k["created_at"]} for k in user_keys]


@router.delete("/metrics-keys/{key_prefix}")
async def delete_metrics_key(
    key_prefix: str,
    user: User = Depends(get_current_active_user),
):
    """Delete a metrics API key by its prefix."""
    user_keys = _metrics_keys.get(str(user.id), [])
    for i, k in enumerate(user_keys):
        if k["key"].startswith(key_prefix) or k["key"][:12] == key_prefix:
            user_keys.pop(i)
            return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Key not found")

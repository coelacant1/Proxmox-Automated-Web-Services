"""Alarm evaluator - checks metric values against alarm thresholds.

Designed to be called periodically (e.g., every 60 seconds via Celery/scheduler).
Fetches current metrics for each active alarm's resource, evaluates conditions,
and transitions alarm state (ok -> alarm, alarm -> ok).
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Alarm, Resource
from app.services.proxmox_client import get_pve

logger = logging.getLogger(__name__)

# Comparison operators
COMPARISONS = {
    "gt": lambda v, t: v > t,
    "gte": lambda v, t: v >= t,
    "lt": lambda v, t: v < t,
    "lte": lambda v, t: v <= t,
    "eq": lambda v, t: v == t,
}


async def evaluate_alarms(db: AsyncSession) -> dict:
    """Evaluate all active alarms and update states."""
    result = await db.execute(select(Alarm).where(Alarm.is_active.is_(True)))
    alarms = result.scalars().all()

    stats = {"evaluated": 0, "triggered": 0, "resolved": 0, "errors": 0}

    for alarm in alarms:
        try:
            resource = await db.get(Resource, alarm.resource_id)
            if not resource or resource.status == "destroyed":
                alarm.state = "insufficient_data"
                alarm.last_evaluated_at = datetime.now(UTC)
                continue

            metric_value = _get_metric_value(resource, alarm.metric)
            if metric_value is None:
                alarm.state = "insufficient_data"
                alarm.last_evaluated_at = datetime.now(UTC)
                stats["evaluated"] += 1
                continue

            comparator = COMPARISONS.get(alarm.comparison)
            if not comparator:
                stats["errors"] += 1
                continue

            triggered = comparator(metric_value, alarm.threshold)
            old_state = alarm.state
            new_state = "alarm" if triggered else "ok"

            if old_state != new_state:
                alarm.state = new_state
                alarm.last_state_change_at = datetime.now(UTC)
                if new_state == "alarm":
                    stats["triggered"] += 1
                    logger.info(
                        "Alarm %s triggered: %s %s %s (value: %s)",
                        alarm.name,
                        alarm.metric,
                        alarm.comparison,
                        alarm.threshold,
                        metric_value,
                    )
                else:
                    stats["resolved"] += 1
                    logger.info("Alarm %s resolved: %s", alarm.name, alarm.metric)

            alarm.last_evaluated_at = datetime.now(UTC)
            stats["evaluated"] += 1

        except Exception:
            logger.exception("Error evaluating alarm %s", alarm.id)
            stats["errors"] += 1

    await db.commit()
    return stats


def _get_metric_value(resource: Resource, metric: str) -> float | None:
    """Fetch current metric value from Proxmox."""
    try:
        pve = get_pve(resource.cluster_id)
        vmtype = "lxc" if resource.resource_type == "lxc" else "qemu"
        if vmtype == "lxc":
            status_data = pve.get_container_status(resource.proxmox_node, resource.proxmox_vmid)
        else:
            status_data = pve.get_vm_status(resource.proxmox_node, resource.proxmox_vmid)

        if metric == "cpu":
            return status_data.get("cpu", 0) * 100  # Convert to percentage
        if metric == "memory":
            maxmem = status_data.get("maxmem", 1)
            return (status_data.get("mem", 0) / max(maxmem, 1)) * 100
        if metric == "disk":
            maxdisk = status_data.get("maxdisk", 1)
            return (status_data.get("disk", 0) / max(maxdisk, 1)) * 100
        if metric == "netin":
            return status_data.get("netin", 0)
        if metric == "netout":
            return status_data.get("netout", 0)
        if metric == "diskread":
            return status_data.get("diskread", 0)
        if metric == "diskwrite":
            return status_data.get("diskwrite", 0)
    except Exception:
        logger.exception("Failed to fetch metric %s for resource %s", metric, resource.id)
    return None

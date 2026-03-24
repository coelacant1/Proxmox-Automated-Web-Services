"""Backup scheduler service.

Evaluates due backup plans and dispatches vzdump tasks.
Designed for periodic execution via Celery Beat or similar scheduler.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Backup, BackupPlan, Resource
from app.services.proxmox_client import proxmox_client

logger = logging.getLogger(__name__)


async def evaluate_due_plans(db: AsyncSession) -> list[dict]:
    """Check all active backup plans and execute overdue ones."""
    result = await db.execute(select(BackupPlan).where(BackupPlan.is_active.is_(True)))
    plans = result.scalars().all()
    executed = []

    for plan in plans:
        if not _is_plan_due(plan):
            continue

        try:
            backup_record = await _execute_backup(db, plan)
            executed.append(
                {
                    "plan_id": str(plan.id),
                    "resource_id": str(plan.resource_id),
                    "backup_id": str(backup_record.id),
                    "status": "dispatched",
                }
            )
        except Exception:
            logger.exception("Failed to execute backup plan %s", plan.id)
            executed.append(
                {
                    "plan_id": str(plan.id),
                    "resource_id": str(plan.resource_id),
                    "status": "failed",
                }
            )

    return executed


def _is_plan_due(plan: BackupPlan) -> bool:
    """Check if a backup plan is due for execution based on last run and schedule."""
    if plan.last_run_at is None:
        return True

    now = datetime.now(UTC)
    elapsed = (now - plan.last_run_at).total_seconds()

    # Simple interval check based on cron expression pattern
    cron = plan.schedule_cron.strip()
    if cron.startswith("0 "):
        # Hourly or daily cron - check if enough time has passed
        parts = cron.split()
        if len(parts) >= 5:
            hour_field = parts[1]
            if hour_field == "*":
                return elapsed >= 3600  # hourly
            return elapsed >= 86400  # daily

    return elapsed >= 86400  # default: daily


async def _execute_backup(db: AsyncSession, plan: BackupPlan) -> Backup:
    """Execute a backup for the given plan."""
    result = await db.execute(select(Resource).where(Resource.id == plan.resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise ValueError(f"Resource {plan.resource_id} not found")

    node = resource.proxmox_node
    vmid = resource.proxmox_vmid

    storage = "local"
    mode = "snapshot" if plan.backup_type == "snapshot" else "stop"

    upid = proxmox_client.create_backup(node, vmid, storage=storage, mode=mode)

    backup = Backup(
        id=uuid.uuid4(),
        resource_id=resource.id,
        owner_id=plan.owner_id,
        backup_type=plan.backup_type,
        status="running",
        notes=f"Scheduled backup from plan: {plan.name} | UPID: {upid}",
    )
    db.add(backup)

    plan.last_run_at = datetime.now(UTC)
    await db.commit()

    logger.info("Dispatched backup for plan %s, resource %s, UPID: %s", plan.id, resource.id, upid)
    return backup


async def cleanup_old_backups(db: AsyncSession, plan: BackupPlan) -> int:
    """Remove backups exceeding retention count for a plan."""
    result = await db.execute(
        select(Backup).where(Backup.plan_id == plan.id, Backup.status == "completed").order_by(Backup.created_at.desc())
    )
    backups = list(result.scalars().all())

    if len(backups) <= plan.retention_count:
        return 0

    to_delete = backups[plan.retention_count :]
    deleted = 0
    for backup in to_delete:
        backup.status = "expired"
        deleted += 1

    await db.commit()
    logger.info("Marked %d old backups as expired for plan %s", deleted, plan.id)
    return deleted

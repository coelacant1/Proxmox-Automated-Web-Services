"""Periodic tasks: enforce resource and account lifecycle policies."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from celery import shared_task

log = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _enforce_lifecycle():
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.core.database import async_session_factory
    from app.models.models import Resource, SystemSetting, User
    from app.services.proxmox_client import proxmox_client

    async with async_session_factory() as db:
        result = await db.execute(
            select(SystemSetting).where(
                SystemSetting.key.in_(["idle_shutdown_days", "idle_destroy_days"])
            )
        )
        settings = {s.key: s.value for s in result.scalars().all()}
        default_shutdown = int(settings.get("idle_shutdown_days", "14") or "0")
        default_destroy = int(settings.get("idle_destroy_days", "30") or "0")

        if default_shutdown <= 0 and default_destroy <= 0:
            log.info("Resource lifecycle policies disabled globally, skipping")
            return {"shutdown": 0, "destroyed": 0}

        now = datetime.now(timezone.utc)
        shutdown_count = 0
        destroy_count = 0

        # Idle shutdown: power down running instances that haven't been accessed
        if default_shutdown > 0:
            resources = await db.execute(
                select(Resource).where(
                    Resource.resource_type.in_(["vm", "lxc"]),
                    Resource.status == "running",
                    Resource.termination_protected.is_(False),
                )
            )
            for r in resources.scalars().all():
                # Check tier override for the resource owner
                owner_result = await db.execute(
                    select(User).options(selectinload(User.tier)).where(User.id == r.owner_id)
                )
                owner = owner_result.scalar_one_or_none()
                shutdown_days = default_shutdown
                if owner and owner.tier and owner.tier.idle_shutdown_days is not None:
                    shutdown_days = owner.tier.idle_shutdown_days
                if shutdown_days <= 0:
                    continue  # tier exempts this user

                cutoff = now - timedelta(days=shutdown_days)
                last_access = r.last_accessed_at or r.created_at
                if last_access and last_access < cutoff:
                    try:
                        if r.proxmox_vmid and r.proxmox_node:
                            if r.resource_type == "lxc":
                                proxmox_client.stop_container(r.proxmox_node, r.proxmox_vmid)
                            else:
                                proxmox_client.shutdown_vm(r.proxmox_node, r.proxmox_vmid)
                            r.status = "stopped"
                            shutdown_count += 1
                            log.info(
                                "Idle shutdown: %s (VMID %s) - last accessed %s",
                                r.display_name, r.proxmox_vmid, last_access,
                            )
                    except Exception:
                        log.exception("Failed to shutdown idle resource %s", r.id)

        # Idle destroy: remove stopped instances past the destroy threshold
        if default_destroy > 0:
            resources = await db.execute(
                select(Resource).where(
                    Resource.resource_type.in_(["vm", "lxc"]),
                    Resource.status == "stopped",
                    Resource.termination_protected.is_(False),
                )
            )
            for r in resources.scalars().all():
                owner_result = await db.execute(
                    select(User).options(selectinload(User.tier)).where(User.id == r.owner_id)
                )
                owner = owner_result.scalar_one_or_none()
                destroy_days = default_destroy
                if owner and owner.tier and owner.tier.idle_destroy_days is not None:
                    destroy_days = owner.tier.idle_destroy_days
                if destroy_days <= 0:
                    continue

                cutoff = now - timedelta(days=destroy_days)
                last_access = r.last_accessed_at or r.updated_at or r.created_at
                if last_access and last_access < cutoff:
                    try:
                        if r.proxmox_vmid and r.proxmox_node:
                            if r.resource_type == "lxc":
                                proxmox_client.delete_container(r.proxmox_node, r.proxmox_vmid)
                            else:
                                proxmox_client.delete_vm(r.proxmox_node, r.proxmox_vmid)
                        r.status = "destroyed"
                        destroy_count += 1
                        log.info(
                            "Idle destroy: %s (VMID %s) - last accessed %s",
                            r.display_name, r.proxmox_vmid, last_access,
                        )
                    except Exception:
                        log.exception("Failed to destroy idle resource %s", r.id)

        await db.commit()
        return {"shutdown": shutdown_count, "destroyed": destroy_count}


async def _enforce_account_lifecycle():
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.core.database import async_session_factory
    from app.models.models import User, SystemSetting
    from app.services.user_cleanup import purge_user

    async with async_session_factory() as db:
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == "account_inactive_days")
        )
        setting = result.scalar_one_or_none()
        default_inactive = int(setting.value if setting else "0")

        if default_inactive <= 0:
            log.info("Account inactivity policy disabled, skipping")
            return {"purged": 0}

        now = datetime.now(timezone.utc)
        purged = 0

        result = await db.execute(
            select(User).options(selectinload(User.tier)).where(
                User.is_superuser.is_(False),
                User.is_active.is_(True),
            )
        )
        users = result.scalars().all()
        for u in users:
            # Check tier override
            inactive_days = default_inactive
            if u.tier and u.tier.account_inactive_days is not None:
                inactive_days = u.tier.account_inactive_days
            if inactive_days <= 0:
                continue  # tier exempts this user

            cutoff = now - timedelta(days=inactive_days)
            last_activity = u.last_login_at or u.created_at
            if last_activity and last_activity < cutoff:
                try:
                    log.info(
                        "Purging inactive account: %s (%s) - last login %s",
                        u.username, u.email, last_activity,
                    )
                    await purge_user(db, u.id)
                    purged += 1
                except Exception:
                    log.exception("Failed to purge inactive user %s", u.id)

        return {"purged": purged}


async def _enforce_quota():
    """Shut down running instances for users who exceed their quota."""
    import json as _json
    from sqlalchemy import select, func
    from app.core.database import async_session_factory
    from app.models.models import Resource, User, UserQuota
    from app.services.proxmox_client import proxmox_client

    async with async_session_factory() as db:
        # Get all users with running resources
        result = await db.execute(
            select(Resource.owner_id).where(
                Resource.resource_type.in_(["vm", "lxc"]),
                Resource.status == "running",
            ).distinct()
        )
        owner_ids = [row[0] for row in result.all()]
        shutdown_count = 0

        for owner_id in owner_ids:
            # Get user's quota
            q_res = await db.execute(select(UserQuota).where(UserQuota.user_id == owner_id))
            quota = q_res.scalar_one_or_none()
            if not quota:
                continue

            # Get all active (non-destroyed) resources and sum usage
            res_result = await db.execute(
                select(Resource).where(
                    Resource.owner_id == owner_id,
                    Resource.status.in_(["running", "stopped", "provisioning", "paused", "suspended"]),
                )
            )
            resources = list(res_result.scalars().all())

            total_vcpus = 0
            total_ram_mb = 0
            total_disk_gb = 0
            vm_count = 0
            ct_count = 0
            for r in resources:
                if r.resource_type == "vm":
                    vm_count += 1
                elif r.resource_type == "lxc":
                    ct_count += 1
                if r.specs:
                    specs = _json.loads(r.specs)
                    total_vcpus += specs.get("cores", 0)
                    total_ram_mb += specs.get("memory_mb", 0)
                    total_disk_gb += specs.get("disk_gb", 0)

            over_quota = (
                vm_count > quota.max_vms
                or ct_count > quota.max_containers
                or total_vcpus > quota.max_vcpus
                or total_ram_mb > quota.max_ram_mb
                or total_disk_gb > quota.max_disk_gb
            )

            if not over_quota:
                continue

            # Get user info for logging
            u_res = await db.execute(select(User).where(User.id == owner_id))
            user = u_res.scalar_one_or_none()
            username = user.username if user else str(owner_id)

            log.warning(
                "User %s over quota (VMs: %d/%d, CTs: %d/%d, vCPUs: %d/%d, RAM: %d/%dMB, Disk: %d/%dGB) - shutting down running instances",
                username, vm_count, quota.max_vms, ct_count, quota.max_containers,
                total_vcpus, quota.max_vcpus, total_ram_mb, quota.max_ram_mb,
                total_disk_gb, quota.max_disk_gb,
            )

            # Shut down running instances (newest first) until under quota
            running = [r for r in resources if r.status == "running" and not r.termination_protected]
            running.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

            for r in running:
                try:
                    if r.proxmox_vmid and r.proxmox_node:
                        if r.resource_type == "lxc":
                            proxmox_client.stop_container(r.proxmox_node, r.proxmox_vmid)
                        else:
                            proxmox_client.shutdown_vm(r.proxmox_node, r.proxmox_vmid)
                    r.status = "stopped"
                    shutdown_count += 1
                    log.info("Over-quota shutdown: %s (VMID %s, user %s)", r.display_name, r.proxmox_vmid, username)

                    # Create a notification event
                    from app.models.models import Event
                    event = Event(
                        event_type="quota_exceeded",
                        source="system",
                        resource_id=r.id,
                        user_id=owner_id,
                        severity="warning",
                        message=f"Instance '{r.display_name}' was shut down because your resource usage exceeds your quota. Please reduce usage or request a quota increase.",
                    )
                    db.add(event)
                except Exception:
                    log.exception("Failed to shut down over-quota resource %s", r.id)

        await db.commit()
        return {"shutdown": shutdown_count}


@shared_task(name="paws.enforce_resource_lifecycle")
def enforce_resource_lifecycle():
    """Celery task: shut down / destroy idle resources per admin policy."""
    result = _run_async(_enforce_lifecycle())
    log.info("Resource lifecycle enforcement complete: %s", result)
    return result


@shared_task(name="paws.enforce_account_lifecycle")
def enforce_account_lifecycle():
    """Celery task: purge inactive user accounts per admin policy."""
    result = _run_async(_enforce_account_lifecycle())
    log.info("Account lifecycle enforcement complete: %s", result)
    return result


@shared_task(name="paws.enforce_quota")
def enforce_quota():
    """Celery task: shut down instances for users exceeding their quota."""
    result = _run_async(_enforce_quota())
    log.info("Quota enforcement complete: %s", result)
    return result

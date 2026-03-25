"""Complete user cleanup: destroy all Proxmox resources and purge DB records."""

import logging
import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    VPC,
    Alarm,
    AuditLog,
    Backup,
    BackupPlan,
    BugReport,
    CustomMetric,
    DNSRecord,
    DocPage,
    Event,
    GroupResourceShare,
    LifecyclePolicy,
    Project,
    ProjectMember,
    QuotaRequest,
    Resource,
    SecurityGroup,
    ServiceEndpoint,
    SSHKeyPair,
    StorageBucket,
    TemplateRequest,
    TierRequest,
    User,
    UserGroup,
    UserGroupMember,
    UserQuota,
    Volume,
)

log = logging.getLogger(__name__)


async def purge_user(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Destroy all Proxmox resources owned by user and delete all DB records.

    Returns a summary dict of what was cleaned up.
    """
    from app.services.proxmox_client import proxmox_client

    summary: dict[str, int] = {}

    # 1. Destroy VMs/containers on Proxmox
    result = await db.execute(
        select(Resource).where(
            Resource.owner_id == user_id,
            Resource.resource_type.in_(["vm", "lxc"]),
            Resource.status != "destroyed",
        )
    )
    resources = result.scalars().all()
    for r in resources:
        if r.proxmox_vmid and r.proxmox_node:
            try:
                if r.resource_type == "lxc":
                    try:
                        proxmox_client.stop_container(r.proxmox_node, r.proxmox_vmid)
                    except Exception:
                        pass
                    proxmox_client.delete_container(r.proxmox_node, r.proxmox_vmid)
                else:
                    try:
                        proxmox_client.stop_vm(r.proxmox_node, r.proxmox_vmid)
                    except Exception:
                        pass
                    proxmox_client.delete_vm(r.proxmox_node, r.proxmox_vmid)
            except Exception:
                log.exception("Failed to destroy %s VMID %s for user %s", r.resource_type, r.proxmox_vmid, user_id)
    summary["proxmox_resources"] = len(resources)

    # 2. Delete Proxmox pool
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user:
        try:
            pool_name = proxmox_client.get_pool_name_for_user(user.username)
            proxmox_client.delete_pool(pool_name)
        except Exception:
            log.debug("Pool cleanup skipped for user %s", user.username)

    # 3. Delete volumes on Proxmox
    vol_result = await db.execute(select(Volume).where(Volume.owner_id == user_id))
    volumes = vol_result.scalars().all()
    for v in volumes:
        if v.proxmox_volid:
            try:
                node = v.proxmox_node if hasattr(v, "proxmox_node") else None
                if node:
                    proxmox_client.delete_volume(node, v.storage, v.proxmox_volid)
            except Exception:
                log.debug("Volume cleanup skipped for %s", v.proxmox_volid)
    summary["volumes"] = len(volumes)

    # 4. Delete all owned DB records (order matters for FK constraints)
    # Groups owned by this user (cascades to members + shares via ORM)
    groups_result = await db.execute(select(UserGroup).where(UserGroup.owner_id == user_id))
    owned_groups = groups_result.scalars().all()
    for g in owned_groups:
        await db.delete(g)
    summary["groups_owned"] = len(owned_groups)

    # Remove user from groups they're a member of
    r = await db.execute(delete(UserGroupMember).where(UserGroupMember.user_id == user_id))
    summary["group_memberships"] = r.rowcount

    # Shares this user created
    r = await db.execute(delete(GroupResourceShare).where(GroupResourceShare.shared_by == user_id))
    summary["group_shares"] = r.rowcount

    # Backups and backup plans
    r = await db.execute(delete(Backup).where(Backup.owner_id == user_id))
    summary["backups"] = r.rowcount
    r = await db.execute(delete(BackupPlan).where(BackupPlan.owner_id == user_id))
    summary["backup_plans"] = r.rowcount

    # Networking
    r = await db.execute(delete(SecurityGroup).where(SecurityGroup.owner_id == user_id))
    summary["security_groups"] = r.rowcount
    r = await db.execute(delete(VPC).where(VPC.owner_id == user_id))
    summary["vpcs"] = r.rowcount
    r = await db.execute(delete(DNSRecord).where(DNSRecord.owner_id == user_id))
    summary["dns_records"] = r.rowcount
    r = await db.execute(delete(ServiceEndpoint).where(ServiceEndpoint.owner_id == user_id))
    summary["service_endpoints"] = r.rowcount

    # Storage
    r = await db.execute(delete(StorageBucket).where(StorageBucket.owner_id == user_id))
    summary["storage_buckets"] = r.rowcount
    r = await db.execute(delete(Volume).where(Volume.owner_id == user_id))
    summary["volumes_db"] = r.rowcount

    # Monitoring
    r = await db.execute(delete(Alarm).where(Alarm.owner_id == user_id))
    summary["alarms"] = r.rowcount
    r = await db.execute(delete(CustomMetric).where(CustomMetric.owner_id == user_id))
    summary["custom_metrics"] = r.rowcount
    r = await db.execute(delete(LifecyclePolicy).where(LifecyclePolicy.owner_id == user_id))
    summary["lifecycle_policies"] = r.rowcount

    # Compute resources
    r = await db.execute(delete(Resource).where(Resource.owner_id == user_id))
    summary["resources"] = r.rowcount

    # SSH keys
    r = await db.execute(delete(SSHKeyPair).where(SSHKeyPair.owner_id == user_id))
    summary["ssh_keys"] = r.rowcount

    # Doc pages
    r = await db.execute(delete(DocPage).where(DocPage.owner_id == user_id))
    summary["doc_pages"] = r.rowcount

    # Projects (members cascade via ORM)
    projects_result = await db.execute(select(Project).where(Project.owner_id == user_id))
    for p in projects_result.scalars().all():
        await db.delete(p)

    # Requests (user_id is NOT NULL, must delete)
    r = await db.execute(delete(QuotaRequest).where(QuotaRequest.user_id == user_id))
    summary["quota_requests"] = r.rowcount
    r = await db.execute(delete(TemplateRequest).where(TemplateRequest.user_id == user_id))
    summary["template_requests"] = r.rowcount
    r = await db.execute(delete(TierRequest).where(TierRequest.user_id == user_id))
    summary["tier_requests"] = r.rowcount

    # Nullify reviewed_by references (nullable FK)
    await db.execute(update(QuotaRequest).where(QuotaRequest.reviewed_by == user_id).values(reviewed_by=None))
    await db.execute(update(TemplateRequest).where(TemplateRequest.reviewed_by == user_id).values(reviewed_by=None))
    await db.execute(update(TierRequest).where(TierRequest.reviewed_by == user_id).values(reviewed_by=None))

    # API keys (from api_keys table)
    from sqlalchemy import text

    await db.execute(text("DELETE FROM api_keys WHERE user_id = :uid"), {"uid": str(user_id)})

    # Bug reports
    r = await db.execute(delete(BugReport).where(BugReport.user_id == user_id))
    summary["bug_reports"] = r.rowcount

    # Nullify audit logs and events (historical records, keep but de-link)
    await db.execute(update(Event).where(Event.user_id == user_id).values(user_id=None))
    # AuditLog.user_id is NOT NULL so we must delete
    r = await db.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
    summary["audit_logs"] = r.rowcount

    # UserQuota and ProjectMember handled by ORM cascade on User delete
    # but we clean them explicitly in case of direct purge
    r = await db.execute(delete(UserQuota).where(UserQuota.user_id == user_id))
    r = await db.execute(delete(ProjectMember).where(ProjectMember.user_id == user_id))

    # Finally delete the user
    if user:
        await db.delete(user)

    await db.commit()
    log.info("Purged user %s: %s", user_id, summary)
    return summary

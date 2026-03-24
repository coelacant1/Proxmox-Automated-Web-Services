"""Admin system settings management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.models import SystemSetting, User
from app.schemas.schemas import SystemSettingRead, SystemSettingUpdate

router = APIRouter(prefix="/api/admin/settings", tags=["admin"])

# Keys that non-admin users can read (for UI behavior)
PUBLIC_SETTING_KEYS = {"session_timeout_minutes", "local_auth_enabled", "platform_name"}

# All known settings with default values - auto-seeded on first list
KNOWN_SETTINGS: dict[str, tuple[str, str | None]] = {
    # Resource Quotas
    "default_max_vms": ("10", "Default max VMs per user"),
    "default_max_containers": ("10", "Default max containers per user"),
    "default_max_vcpus": ("32", "Default max vCPUs per user"),
    "default_max_ram_mb": ("65536", "Default max RAM (MB) per user"),
    "default_max_disk_gb": ("500", "Default max disk (GB) per user"),
    "default_max_networks": ("5", "Default max networks per user"),
    "default_max_volumes": ("20", "Default max volumes per user"),
    "default_max_volume_size_gb": ("500", "Default max volume size (GB)"),
    "default_max_security_groups": ("10", "Default max security groups per user"),
    "default_max_sg_rules": ("50", "Default max rules per security group"),
    "default_max_backups": ("20", "Default max backups per user"),
    "default_max_backup_size_gb": ("100", "Default max backup storage (GB) per user"),
    "default_max_snapshots": ("10", "Default max snapshots per user"),
    "default_max_buckets": ("5", "Default max S3 buckets per user"),
    "default_max_storage_gb": ("50", "Default max S3 storage (GB) per user"),
    # Cluster Settings
    "cpu_overcommit_ratio": ("4", "CPU overcommit ratio for placement"),
    "ram_overcommit_ratio": ("1.5", "RAM overcommit ratio for placement"),
    "placement_strategy": ("balanced", "VM placement strategy (balanced/packed)"),
    "vmid_range_start": ("1000", "Start of VMID range for new instances"),
    "vmid_range_end": ("99999", "End of VMID range for new instances"),
    # SDN / Networking
    "sdn.default_max_subnet_prefix": ("24", "Default maximum subnet prefix (e.g. 24 = /24, 254 hosts)"),
    "sdn.lan_ranges": ('["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"]', "RFC1918 ranges blocked in published mode"),
    "sdn.upstream_ips": ("[]", "Upstream proxy IPs whitelisted in published mode (JSON array)"),
    # Authentication
    "registration_mode": ("open", "Registration mode (open/closed/invite)"),
    "session_timeout_minutes": ("1440", "Session timeout in minutes"),
    # Resource Lifecycle
    "idle_shutdown_days": ("7", "Days before idle resources are shut down"),
    "idle_destroy_days": ("30", "Days before idle resources are destroyed"),
    # Account Lifecycle
    "account_inactive_days": ("90", "Days before inactive accounts are purged"),
    # General
    "motd": ("", "Message of the day displayed on dashboard"),
}


@router.get("/public")
async def get_public_settings(db: AsyncSession = Depends(get_db)):
    """Return non-sensitive system settings (no auth required)."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key.in_(PUBLIC_SETTING_KEYS)))
    return {s.key: s.value for s in result.scalars().all()}


@router.get("/", response_model=list[SystemSettingRead])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all system settings, auto-seeding any missing known settings."""
    result = await db.execute(select(SystemSetting).order_by(SystemSetting.key))
    existing = {s.key: s for s in result.scalars().all()}
    seeded = False
    for key, (default_value, description) in KNOWN_SETTINGS.items():
        if key not in existing:
            s = SystemSetting(key=key, value=default_value, description=description)
            db.add(s)
            existing[key] = s
            seeded = True
    if seeded:
        await db.commit()
    return sorted(existing.values(), key=lambda s: s.key)


@router.get("/{key}", response_model=SystemSettingRead)
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    return setting


@router.patch("/{key}", response_model=SystemSettingRead)
async def update_setting(
    key: str,
    data: SystemSettingUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        setting = SystemSetting(key=key, value=data.value, description=None)
        db.add(setting)
    else:
        setting.value = data.value
    await db.commit()
    await db.refresh(setting)
    return setting

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
    # SMTP / Email Notifications
    "smtp_enabled": ("false", "Enable email notifications via SMTP"),
    "smtp_host": ("", "SMTP server hostname"),
    "smtp_port": ("587", "SMTP server port"),
    "smtp_username": ("", "SMTP authentication username"),
    "smtp_password": ("", "SMTP authentication password"),
    "smtp_from_address": ("paws@localhost", "Sender email address"),
    "smtp_from_name": ("PAWS", "Sender display name"),
    "smtp_use_tls": ("true", "Use STARTTLS for SMTP connection"),
    # General
    "motd": ("", "Message of the day displayed on dashboard"),
    # S3 Storage (Ceph RadosGW / MinIO)
    "s3_endpoint_url": ("", "S3-compatible storage endpoint URL"),
    "s3_access_key": ("", "S3 access key (admin/RadosGW key)"),
    "s3_secret_key": ("", "S3 secret key (encrypted)"),
    "s3_region": ("us-east-1", "S3 region name"),
    # OAuth / OIDC
    "oauth_enabled": ("false", "Enable OAuth2/OIDC login"),
    "oauth_provider_url": ("", "OAuth2/OIDC provider URL (e.g. Authentik)"),
    "oauth_client_id": ("", "OAuth2 client ID"),
    "oauth_client_secret": ("", "OAuth2 client secret (encrypted)"),
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
    # Mask encrypted values in response
    items = sorted(existing.values(), key=lambda s: s.key)
    for s in items:
        if s.is_encrypted and s.value:
            s.value = "********"
    return items


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
    from app.core.config_resolver import ENCRYPTED_KEYS

    should_encrypt = key in ENCRYPTED_KEYS
    stored_value = data.value
    if should_encrypt and data.value:
        from app.core.encryption import encrypt

        stored_value = encrypt(data.value)

    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        setting = SystemSetting(key=key, value=stored_value, description=None, is_encrypted=should_encrypt)
        db.add(setting)
    else:
        setting.value = stored_value
        setting.is_encrypted = should_encrypt
    await db.commit()
    await db.refresh(setting)

    # Invalidate service caches when relevant keys change
    if key.startswith("s3_"):
        from app.services.storage_service import storage_service

        storage_service.invalidate_config()
    elif key.startswith("oauth_"):
        from app.services.oauth_service import oauth_service

        oauth_service.invalidate_config()

    return setting


@router.post("/smtp/test")
async def send_test_email(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Send a test email to the current admin user to verify SMTP settings."""
    from app.services.email_service import get_smtp_config, render_template, send_email

    smtp_config = await get_smtp_config(db)
    if smtp_config.get("smtp_enabled", "false").lower() != "true":
        raise HTTPException(status_code=400, detail="SMTP is not enabled. Enable smtp_enabled first.")
    if not smtp_config.get("smtp_host"):
        raise HTTPException(status_code=400, detail="SMTP host is not configured.")

    subject, html_body, text_body = render_template("test", {})
    success = await send_email(admin.email, subject, html_body, text_body, smtp_config)
    if not success:
        raise HTTPException(status_code=502, detail="Failed to send test email. Check SMTP settings and server logs.")
    return {"status": "ok", "sent_to": admin.email}

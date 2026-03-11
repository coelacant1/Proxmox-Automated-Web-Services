import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.core.middleware import AnalyticsMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from app.core.security import hash_password
from app.models.models import InstanceType, SystemSetting, User, UserQuota, UserRole
from app.routers import (
    admin,
    admin_audit,
    admin_groups,
    admin_quota_requests,
    admin_ha,
    admin_settings,
    admin_templates,
    admin_tiers,
    api_keys,
    auth,
    backups,
    billing,
    bug_reports,
    cluster,
    compute,
    console,
    dashboard,
    dns,
    endpoints,
    events,
    groups,
    health,
    health_checks,
    instance_types,
    lifecycle_policies,
    logs,
    mfa,
    migration,
    monitoring,
    networking,
    notifications,
    placement,
    projects,
    proxmox,
    quota_requests,
    resources,
    search,
    security_groups,
    ssh_keys,
    storage,
    storage_pools,
    system_rules,
    tags,
    template_requests,
    templates,
    volumes,
    vpcs,
)

logger = logging.getLogger(__name__)


def validate_security_settings() -> None:
    """Check for dangerous default settings at startup."""
    if settings.has_insecure_secret_key:
        if not settings.debug:
            logger.critical(
                "FATAL: JWT secret_key is set to the default value. "
                "Generate a key with: python -c \"import secrets; print(secrets.token_hex(32))\" "
                "and set PAWS_SECRET_KEY in your .env file."
            )
            sys.exit(1)
        logger.warning(
            "WARNING: JWT secret_key is set to the default value. "
            "Set PAWS_SECRET_KEY in your .env before deploying."
        )

    if settings.has_insecure_admin_password:
        logger.warning(
            "WARNING: Default admin password is 'changeme'. "
            "Set PAWS_DEFAULT_ADMIN_PASSWORD in your .env or change it after first login."
        )

    if not settings.proxmox_verify_ssl:
        logger.warning(
            "WARNING: Proxmox SSL verification is disabled (PAWS_PROXMOX_VERIFY_SSL=false). "
            "Enable it in production with a valid certificate."
        )

    if not settings.debug:
        for origin in settings.cors_origin_list:
            if "localhost" in origin or "127.0.0.1" in origin:
                logger.warning(
                    "WARNING: CORS origin '%s' includes localhost in non-debug mode. "
                    "Update PAWS_CORS_ORIGINS for production.",
                    origin,
                )


async def seed_default_admin() -> None:
    """Create a default admin account if no admin user exists yet."""
    import secrets as _secrets

    try:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.role == UserRole.ADMIN).limit(1))
            if result.scalar_one_or_none() is not None:
                return

            # Use configured password, or generate a cryptographic random one
            if settings.has_insecure_admin_password:
                generated_password = _secrets.token_urlsafe(24)
                admin_password = generated_password
            else:
                generated_password = None
                admin_password = settings.default_admin_password

            admin_user = User(
                email=settings.default_admin_email,
                username=settings.default_admin_username,
                hashed_password=hash_password(admin_password),
                full_name="PAWS Administrator",
                role=UserRole.ADMIN,
                is_superuser=True,
                auth_provider="local",
                must_change_password=True,
            )
            db.add(admin_user)
            await db.flush()
            db.add(UserQuota(user_id=admin_user.id))
            await db.commit()

            if generated_password:
                logger.warning(
                    "Default admin account created (username: %s, password: %s). "
                    "Change this password immediately! This will only be shown once.",
                    settings.default_admin_username,
                    generated_password,
                )
            else:
                logger.warning(
                    "Default admin account created (username: %s). Change the password immediately!",
                    settings.default_admin_username,
                )
    except Exception:
        logger.warning("Could not seed admin account - have you run 'alembic upgrade head'?")


SYSTEM_SETTING_DEFAULTS = {
    "default_quota_max_vms": ("5", "Default max VMs for new users"),
    "default_quota_max_containers": ("10", "Default max containers for new users"),
    "default_quota_max_vcpus": ("16", "Default max vCPUs for new users"),
    "default_quota_max_ram_mb": ("32768", "Default max RAM (MB) for new users"),
    "default_quota_max_disk_gb": ("500", "Default max disk (GB) for new users"),
    "default_quota_max_snapshots": ("10", "Default max snapshots for new users"),
    "overcommit_cpu_ratio": ("4.0", "CPU overcommit ratio (e.g. 4.0 = 4:1)"),
    "overcommit_ram_ratio": ("1.5", "RAM overcommit ratio"),
    "placement_strategy": ("least-loaded", "VM placement strategy: least-loaded, round-robin, manual"),
    "registration_mode": ("open", "User registration: open, approval, disabled"),
    "motd": ("", "Message of the day shown on user dashboard"),
    # Ingress / reverse proxy settings
    "ingress_base_domain": ("", "Base domain for service endpoints (e.g. apps.paws.local)"),
    "ingress_tcp_port_range": ("30000-32767", "TCP port range for non-HTTP endpoints"),
    "ingress_proxy_timeout": ("60", "Default proxy timeout in seconds"),
    "ingress_ssl_mode": ("auto", "SSL mode: auto, manual, off"),
    "ingress_max_endpoints_per_user": ("20", "Max service endpoints per user"),
    # Backup retention defaults
    "backup_retention_last": ("3", "Default backup retention: keep last N"),
    "backup_retention_daily": ("7", "Default backup retention: daily for N days"),
    "backup_retention_weekly": ("4", "Default backup retention: weekly for N weeks"),
    "backup_retention_monthly": ("6", "Default backup retention: monthly for N months"),
    # PBS settings
    "pbs_host": ("", "Proxmox Backup Server hostname"),
    "pbs_port": ("8007", "PBS API port"),
    "pbs_datastore": ("backups", "Default PBS datastore name"),
    "pbs_verify_after_backup": ("true", "Automatically verify backups after completion"),
    # Storage pool configuration
    "storage_pools": ('["local-lvm"]', "Available storage pools (JSON array of pool names)"),
    "default_storage_pool": ("local-lvm", "Default storage pool for new volumes/instances"),
    # Backup storage configuration
    "backup_storages": ('[]', "Proxmox storages enabled for user backups (JSON array)"),
    # VMID range
    "vmid_range_start": ("1000", "Starting VMID for new VMs/containers"),
    "vmid_range_end": ("999999", "Ending VMID for new VMs/containers"),
    # Session management
    "session_timeout_minutes": ("0", "Force logout after N minutes (0 = use token expiry, no forced timeout)"),
    # Resource lifecycle
    "idle_shutdown_days": ("14", "Power down running instances after N days of no access (0 = disabled)"),
    "idle_destroy_days": ("30", "Automatically destroy stopped instances after N days of no access (0 = disabled)"),
    "account_inactive_days": ("0", "Deactivate and purge user accounts after N days of inactivity (0 = disabled)"),
}


async def seed_system_settings() -> None:
    """Insert default system settings if they don't exist."""
    try:
        async with async_session() as db:
            for key, (value, description) in SYSTEM_SETTING_DEFAULTS.items():
                result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
                if result.scalar_one_or_none() is None:
                    db.add(SystemSetting(key=key, value=value, description=description))
            await db.commit()
            logger.info("System settings seeded/verified.")
    except Exception:
        logger.warning("Could not seed system settings - have you run 'alembic upgrade head'?")


DEFAULT_INSTANCE_TYPES = [
    ("paws.nano", 1, 512, 10, "general", "Nano - 1 vCPU, 512 MiB RAM, 10 GiB", 10),
    ("paws.micro", 1, 1024, 20, "general", "Micro - 1 vCPU, 1 GiB RAM, 20 GiB", 20),
    ("paws.small", 2, 2048, 40, "general", "Small - 2 vCPU, 2 GiB RAM, 40 GiB", 30),
    ("paws.medium", 2, 4096, 80, "general", "Medium - 2 vCPU, 4 GiB RAM, 80 GiB", 40),
    ("paws.large", 4, 8192, 160, "general", "Large - 4 vCPU, 8 GiB RAM, 160 GiB", 50),
    ("paws.xlarge", 8, 16384, 320, "general", "XLarge - 8 vCPU, 16 GiB RAM, 320 GiB", 60),
    ("paws.compute.small", 4, 2048, 40, "compute", "Compute Small - 4 vCPU, 2 GiB RAM", 110),
    ("paws.compute.medium", 8, 4096, 40, "compute", "Compute Medium - 8 vCPU, 4 GiB RAM", 120),
    ("paws.compute.large", 16, 8192, 40, "compute", "Compute Large - 16 vCPU, 8 GiB RAM", 130),
    ("paws.memory.small", 2, 8192, 40, "memory", "Memory Small - 2 vCPU, 8 GiB RAM", 210),
    ("paws.memory.medium", 4, 16384, 80, "memory", "Memory Medium - 4 vCPU, 16 GiB RAM", 220),
    ("paws.memory.large", 8, 32768, 160, "memory", "Memory Large - 8 vCPU, 32 GiB RAM", 230),
]


async def seed_instance_types() -> None:
    """Seed default instance types if none exist."""
    try:
        async with async_session() as db:
            result = await db.execute(select(InstanceType).limit(1))
            if result.scalar_one_or_none() is not None:
                return
            for name, vcpus, ram_mib, disk_gib, category, description, sort_order in DEFAULT_INSTANCE_TYPES:
                db.add(InstanceType(
                    name=name, vcpus=vcpus, ram_mib=ram_mib, disk_gib=disk_gib,
                    category=category, description=description, sort_order=sort_order,
                ))
            await db.commit()
            logger.info("Default instance types seeded (%d types).", len(DEFAULT_INSTANCE_TYPES))
    except Exception:
        logger.warning("Could not seed instance types - have you run 'alembic upgrade head'?")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_settings()
    await seed_default_admin()
    await seed_system_settings()
    await seed_instance_types()
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "# Proxmox Automated Web Services (PAWS)\n\n"
        "AWS-like infrastructure platform powered by Proxmox VE.\n\n"
        "## Features\n"
        "- **Compute** - Create and manage VMs and LXC containers from templates\n"
        "- **Networking** - SDN virtual networks, firewall rules\n"
        "- **Storage** - S3-compatible object storage via MinIO\n"
        "- **Backups** - Snapshot creation, rollback, and scheduling\n"
        "- **Auth** - JWT + OAuth2/OIDC (Authentik), API keys, RBAC\n"
        "- **Quotas** - Per-user resource limits enforced at the API layer\n\n"
        "## Authentication\n"
        "Use `POST /api/auth/login` to obtain a JWT access token, then pass it as "
        "`Authorization: Bearer <token>` on subsequent requests. "
        "For programmatic access, create API keys via `POST /api/api-keys`."
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "health", "description": "Service health checks"},
        {"name": "auth", "description": "Authentication - login, register, OAuth2, token refresh"},
        {"name": "admin", "description": "Admin-only user and system management"},
        {"name": "resources", "description": "Generic resource listing for the current user"},
        {"name": "api-keys", "description": "API key management for programmatic access"},
        {"name": "proxmox", "description": "Proxmox cluster status and node inventory"},
        {"name": "compute", "description": "VM and container provisioning, lifecycle, snapshots"},
        {"name": "networking", "description": "SDN zones, VNets, and firewall rules"},
        {"name": "storage", "description": "S3-compatible object storage (MinIO) - buckets and objects"},
        {"name": "backups", "description": "Snapshot and backup management for VMs/containers"},
        {"name": "dashboard", "description": "Dashboard summaries, usage stats, and admin overview"},
        {"name": "notifications", "description": "Real-time WebSocket notifications"},
        {"name": "cluster", "description": "Sanitized cluster health for all users"},
        {"name": "templates", "description": "Template catalog for provisioning"},
        {"name": "quota-requests", "description": "Quota increase requests (AWS-style)"},
    ],
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AnalyticsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-CSRF-Token"],
)

app.include_router(health.router)
app.include_router(billing.router)
app.include_router(health_checks.router)
app.include_router(events.router)
app.include_router(lifecycle_policies.router)
app.include_router(tags.router)
app.include_router(placement.router)
app.include_router(logs.router)
app.include_router(search.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(resources.router)
app.include_router(api_keys.router)
app.include_router(proxmox.router)
app.include_router(compute.router)
app.include_router(console.router)
app.include_router(migration.router)
app.include_router(networking.router)
app.include_router(endpoints.router)
app.include_router(dns.router)
app.include_router(monitoring.router)
app.include_router(storage.router)
app.include_router(storage_pools.router)
app.include_router(backups.router)
app.include_router(dashboard.router)
app.include_router(notifications.router)
app.include_router(cluster.router)
app.include_router(templates.router)
app.include_router(quota_requests.router)
app.include_router(admin_templates.router)
app.include_router(admin_settings.router)
app.include_router(admin_quota_requests.router)
app.include_router(admin_audit.router)
app.include_router(projects.router)
app.include_router(mfa.router)
app.include_router(instance_types.router)
app.include_router(ssh_keys.router)
app.include_router(security_groups.router)
app.include_router(volumes.router)
app.include_router(vpcs.router)
app.include_router(bug_reports.router)
app.include_router(admin_tiers.router)
app.include_router(admin_tiers.user_router)
app.include_router(admin_ha.router)
app.include_router(admin_groups.router)
app.include_router(system_rules.router)
app.include_router(groups.router)
app.include_router(template_requests.router)

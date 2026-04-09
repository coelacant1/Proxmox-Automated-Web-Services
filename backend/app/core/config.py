from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic_settings import BaseSettings


@dataclass
class ClusterConfig:
    """Connection details for a single Proxmox cluster (parsed from env vars)."""

    name: str = "default"
    host: str = ""
    port: int = 8006
    token_id: str = ""
    token_secret: str = ""
    verify_ssl: bool = False
    password: str = ""
    console_user: str = ""
    console_password: str = ""
    # PBS settings (per-cluster)
    pbs_host: str = ""
    pbs_port: int = 8007
    pbs_token_id: str = "root@pam!paws"
    pbs_token_secret: str = ""
    pbs_fingerprint: str = ""
    pbs_datastore: str = "backups"
    pbs_verify_ssl: bool = False


class Settings(BaseSettings):
    app_name: str = "PAWS"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://paws:paws@localhost:5432/paws"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    secret_key: str = "CHANGE-ME-IN-PRODUCTION"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Proxmox (legacy single-cluster - used as fallback when PAWS_CLUSTER_NAMES is unset)
    proxmox_host: str = ""
    proxmox_port: int = 8006
    proxmox_token_id: str = ""
    proxmox_token_secret: str = ""
    proxmox_verify_ssl: bool = False
    proxmox_password: str = ""
    proxmox_console_user: str = ""
    proxmox_console_password: str = ""

    # Multi-cluster support: comma-separated cluster names
    cluster_names: str = ""

    # Auth modes
    local_auth_enabled: bool = True
    oauth_enabled: bool = True
    oauth_provider_url: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""

    # Rate limiting
    rate_limit_per_minute: int = 600
    vm_create_limit_per_hour: int = 5
    auth_login_limit_per_minute: int = 5
    auth_register_limit_per_minute: int = 3

    # CORS
    cors_origins: str = "http://localhost:5173"

    # Default admin account (created on first startup if no admin exists)
    default_admin_username: str = "admin"
    default_admin_email: str = "admin@paws.local"
    default_admin_password: str = "changeme"

    # Password policy
    password_min_length: int = 12
    password_require_uppercase: bool = True
    password_require_lowercase: bool = True
    password_require_digit: bool = True
    password_require_special: bool = True
    password_history_count: int = 5

    # S3 Storage (Ceph RadosGW)
    s3_endpoint_url: str = "http://localhost:7480"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"

    # Proxmox Backup Server (legacy single-cluster - used as fallback)
    pbs_host: str = ""
    pbs_port: int = 8007
    pbs_token_id: str = "root@pam!paws"
    pbs_token_secret: str = ""
    pbs_fingerprint: str = ""
    pbs_datastore: str = "backups"
    pbs_verify_ssl: bool = False

    model_config = {"env_prefix": "PAWS_", "env_file": [".env", "../.env"]}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_insecure_secret_key(self) -> bool:
        return self.secret_key == "CHANGE-ME-IN-PRODUCTION"

    @property
    def has_insecure_admin_password(self) -> bool:
        return self.default_admin_password == "changeme"

    def get_cluster_configs(self) -> list[ClusterConfig]:
        """Parse cluster configurations from environment variables.

        If PAWS_CLUSTER_NAMES is set (e.g. "main,siteb"), reads per-cluster
        vars like PAWS_CLUSTER_MAIN_HOST, PAWS_CLUSTER_MAIN_PORT, etc.

        If PAWS_CLUSTER_NAMES is unset, falls back to legacy PAWS_PROXMOX_*
        vars as a single cluster named "default".
        """
        names = [n.strip() for n in self.cluster_names.split(",") if n.strip()]

        if not names:
            return [
                ClusterConfig(
                    name="default",
                    host=self.proxmox_host,
                    port=self.proxmox_port,
                    token_id=self.proxmox_token_id,
                    token_secret=self.proxmox_token_secret,
                    verify_ssl=self.proxmox_verify_ssl,
                    password=self.proxmox_password,
                    console_user=self.proxmox_console_user,
                    console_password=self.proxmox_console_password,
                    pbs_host=self.pbs_host,
                    pbs_port=self.pbs_port,
                    pbs_token_id=self.pbs_token_id,
                    pbs_token_secret=self.pbs_token_secret,
                    pbs_fingerprint=self.pbs_fingerprint,
                    pbs_datastore=self.pbs_datastore,
                    pbs_verify_ssl=self.pbs_verify_ssl,
                )
            ]

        clusters: list[ClusterConfig] = []
        for name in names:
            prefix = f"PAWS_CLUSTER_{name.upper()}_"
            clusters.append(
                ClusterConfig(
                    name=name,
                    host=os.environ.get(f"{prefix}HOST", ""),
                    port=int(os.environ.get(f"{prefix}PORT", "8006")),
                    token_id=os.environ.get(f"{prefix}TOKEN_ID", ""),
                    token_secret=os.environ.get(f"{prefix}TOKEN_SECRET", ""),
                    verify_ssl=os.environ.get(f"{prefix}VERIFY_SSL", "false").lower() == "true",
                    password=os.environ.get(f"{prefix}PASSWORD", ""),
                    console_user=os.environ.get(f"{prefix}CONSOLE_USER", ""),
                    console_password=os.environ.get(f"{prefix}CONSOLE_PASSWORD", ""),
                    pbs_host=os.environ.get(f"{prefix}PBS_HOST", ""),
                    pbs_port=int(os.environ.get(f"{prefix}PBS_PORT", "8007")),
                    pbs_token_id=os.environ.get(f"{prefix}PBS_TOKEN_ID", "root@pam!paws"),
                    pbs_token_secret=os.environ.get(f"{prefix}PBS_TOKEN_SECRET", ""),
                    pbs_fingerprint=os.environ.get(f"{prefix}PBS_FINGERPRINT", ""),
                    pbs_datastore=os.environ.get(f"{prefix}PBS_DATASTORE", "backups"),
                    pbs_verify_ssl=os.environ.get(f"{prefix}PBS_VERIFY_SSL", "false").lower() == "true",
                )
            )
        return clusters


settings = Settings()

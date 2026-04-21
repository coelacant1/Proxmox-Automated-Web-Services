from __future__ import annotations

from pydantic_settings import BaseSettings


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

    # Default admin account (created on first startup if no admin exists and
    # the setup wizard is skipped). When using the setup wizard (/setup) these
    # values are ignored - the wizard creates the admin account interactively.
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

    # S3 Storage (Ceph RadosGW) - fallback only; prefer Admin UI > Connections
    s3_endpoint_url: str = "http://localhost:7480"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"

    model_config = {"env_prefix": "PAWS_", "env_file": [".env", "../.env"], "extra": "ignore"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_insecure_secret_key(self) -> bool:
        return self.secret_key == "CHANGE-ME-IN-PRODUCTION"

    @property
    def has_insecure_admin_password(self) -> bool:
        return self.default_admin_password == "changeme"


settings = Settings()

"""Resolve configuration values: DB SystemSetting (encrypted or plain) -> env fallback.

Usage:
    value = get_config_value("s3_access_key", encrypted=True)  # async
    value = get_config_value_sync("s3_access_key", encrypted=True)  # sync (for init)
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# Map of config keys to their env-based fallback attribute names on Settings
_ENV_FALLBACKS: dict[str, str] = {
    # S3
    "s3_endpoint_url": "s3_endpoint_url",
    "s3_access_key": "s3_access_key",
    "s3_secret_key": "s3_secret_key",
    "s3_region": "s3_region",
    # OAuth
    "oauth_enabled": "oauth_enabled",
    "oauth_provider_url": "oauth_provider_url",
    "oauth_client_id": "oauth_client_id",
    "oauth_client_secret": "oauth_client_secret",
}

# Keys whose SystemSetting values are encrypted
ENCRYPTED_KEYS = {"s3_secret_key", "oauth_client_secret", "smtp_password"}


async def get_config_value(key: str, default: Any = "") -> Any:
    """Read a config value from DB SystemSetting, falling back to env."""
    try:
        from sqlalchemy import select

        from app.core.database import async_session
        from app.models.models import SystemSetting

        async with async_session() as session:
            result = await session.execute(select(SystemSetting).where(SystemSetting.key == key))
            setting = result.scalar_one_or_none()
            if setting and setting.value:
                if setting.is_encrypted:
                    from app.core.encryption import decrypt

                    return decrypt(setting.value)
                return setting.value
    except Exception:
        pass

    # Env fallback
    attr = _ENV_FALLBACKS.get(key)
    if attr and hasattr(settings, attr):
        val = getattr(settings, attr)
        if val:
            return val
    return default


def get_config_value_sync(key: str, default: Any = "") -> Any:
    """Read a config value synchronously (for service init)."""
    try:
        from sqlalchemy import create_engine, text

        sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
        sync_url = sync_url.replace("postgresql+psycopg2", "postgresql")
        engine = create_engine(sync_url)

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT value, is_encrypted FROM system_settings WHERE key = :k"),
                {"k": key},
            ).fetchone()
            if row and row[0]:
                if row[1]:
                    from app.core.encryption import decrypt

                    return decrypt(row[0])
                return row[0]
        engine.dispose()
    except Exception:
        pass

    attr = _ENV_FALLBACKS.get(key)
    if attr and hasattr(settings, attr):
        val = getattr(settings, attr)
        if val:
            return val
    return default


async def set_config_value(key: str, value: str, description: str | None = None) -> None:
    """Write a config value to DB, encrypting if needed."""
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.models import SystemSetting

    should_encrypt = key in ENCRYPTED_KEYS
    stored_value = value
    if should_encrypt and value:
        from app.core.encryption import encrypt

        stored_value = encrypt(value)

    async with async_session() as session:
        result = await session.execute(select(SystemSetting).where(SystemSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = stored_value
            setting.is_encrypted = should_encrypt
            if description is not None:
                setting.description = description
        else:
            setting = SystemSetting(
                key=key,
                value=stored_value,
                is_encrypted=should_encrypt,
                description=description,
            )
            session.add(setting)
        await session.commit()

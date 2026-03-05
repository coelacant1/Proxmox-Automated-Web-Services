from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def validate_password(password: str) -> str | None:
    """Return an error message if the password doesn't meet policy, or None if valid."""
    if len(password) < settings.password_min_length:
        return f"Password must be at least {settings.password_min_length} characters"
    if settings.password_require_uppercase and not any(c.isupper() for c in password):
        return "Password must contain at least one uppercase letter"
    if settings.password_require_lowercase and not any(c.islower() for c in password):
        return "Password must contain at least one lowercase letter"
    if settings.password_require_digit and not any(c.isdigit() for c in password):
        return "Password must contain at least one digit"
    if settings.password_require_special and not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?`~" for c in password):
        return "Password must contain at least one special character"
    return None


def _generate_jti() -> str:
    """Generate a unique JWT ID for token tracking."""
    import uuid

    return str(uuid.uuid4())


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire, "type": "access", "jti": _generate_jti()})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh", "jti": _generate_jti()})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None


async def is_token_revoked(jti: str) -> bool:
    """Check if a token's jti is in the Redis blocklist."""
    try:
        from app.services.rate_limiter import get_redis

        r = await get_redis()
        return await r.exists(f"revoked:{jti}") > 0
    except Exception:
        return False


async def revoke_token(jti: str, ttl_seconds: int) -> None:
    """Add a token's jti to the Redis blocklist with TTL matching remaining token lifetime."""
    try:
        from app.services.rate_limiter import get_redis

        r = await get_redis()
        await r.setex(f"revoked:{jti}", ttl_seconds, "1")
    except Exception:
        pass


async def revoke_all_user_tokens(user_id: str) -> None:
    """Set a per-user revocation timestamp - all tokens issued before this are invalid."""
    try:
        from app.services.rate_limiter import get_redis

        r = await get_redis()
        now = datetime.now(UTC).timestamp()
        await r.set(f"revoked_before:{user_id}", str(now))
    except Exception:
        pass


async def is_user_tokens_revoked_before(user_id: str, issued_at: float) -> bool:
    """Check if a user's tokens issued before a certain time are revoked."""
    try:
        from app.services.rate_limiter import get_redis

        r = await get_redis()
        revoked_before = await r.get(f"revoked_before:{user_id}")
        if revoked_before and issued_at < float(revoked_before):
            return True
        return False
    except Exception:
        return False

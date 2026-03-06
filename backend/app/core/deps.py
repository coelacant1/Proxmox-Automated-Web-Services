import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Query, Request, WebSocket, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token, is_token_revoked, is_user_tokens_revoked_before
from app.models.models import SystemSetting, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def _extract_token(request: Request, token: str | None) -> str | None:
    """Extract JWT from Bearer header or httpOnly cookie."""
    if token:
        return token
    return request.cookies.get("paws_access_token")


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    jwt_token = _extract_token(request, token)
    if jwt_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(jwt_token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    # Check token revocation via jti
    jti = payload.get("jti")
    if jti and await is_token_revoked(jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    # Check per-user revocation timestamp
    iat = payload.get("iat", 0)
    if await is_user_tokens_revoked_before(user_id, iat):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked")

    # Check admin-configured session timeout
    try:
        result = await db.execute(
            select(SystemSetting.value).where(SystemSetting.key == "session_timeout_minutes")
        )
        timeout_val = result.scalar_one_or_none()
        if timeout_val:
            timeout_minutes = int(timeout_val)
            if timeout_minutes > 0 and iat:
                token_age = datetime.now(timezone.utc).timestamp() - iat
                if token_age > timeout_minutes * 60:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Session expired. Please log in again.",
                    )
    except HTTPException:
        raise
    except Exception:
        pass  # fail open if DB query fails

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


async def get_current_user_ws(
    ws: WebSocket,
    token: str | None = Query(None),
) -> User | None:
    """Authenticate a WebSocket connection via query param token."""
    if token is None:
        return None
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    async for db in get_db():
        result = await db.execute(select(User).where(User.id == uid))
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
    return None


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    return user


def require_role(*roles: str):
    """Dependency that checks if the current user has one of the specified roles."""

    async def role_checker(user: User = Depends(get_current_active_user)) -> User:
        if user.role not in roles and not user.is_superuser:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return role_checker


require_admin = require_role(UserRole.ADMIN)
require_operator = require_role(UserRole.ADMIN, UserRole.OPERATOR)
require_member = require_role(UserRole.ADMIN, UserRole.OPERATOR, UserRole.MEMBER)
require_viewer = require_role(UserRole.ADMIN, UserRole.OPERATOR, UserRole.MEMBER, UserRole.VIEWER)


def require_capability(capability: str):
    """Dependency that checks if the user's tier includes a specific capability.

    Admins and superusers always pass. Capability is checked against the
    user's tier capabilities JSON array.
    """

    async def cap_checker(user: User = Depends(get_current_active_user)) -> User:
        if user.is_superuser or user.role == UserRole.ADMIN:
            return user
        if not user.tier:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your account tier does not include the '{capability}' capability",
            )
        import json

        try:
            caps = json.loads(user.tier.capabilities)
        except (json.JSONDecodeError, TypeError):
            caps = []
        if capability not in caps:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your account tier does not include the '{capability}' capability",
            )
        return user

    return cap_checker

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    revoke_all_user_tokens,
    revoke_token,
    validate_password,
)
from app.models.models import Project, ProjectMember, ProjectRole, SecurityGroup, SecurityGroupRule, User
from app.schemas.schemas import LoginRequest, Token, UserCreate, UserRead
from app.services.audit_service import log_auth_event
from app.services.oauth_service import oauth_service
from app.services.rate_limiter import check_rate_limit
from app.services.user_service import (
    authenticate_local_user,
    create_local_user,
    create_oauth_user,
    get_user_by_email,
    get_user_by_oauth_sub,
    get_user_by_username,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def _check_auth_rate_limit(request: Request, action: str, max_requests: int, window: int) -> None:
    """Apply per-IP rate limiting for auth endpoints."""
    ip = request.client.host if request.client else "unknown"
    key = f"rate:auth:{action}:{ip}"
    try:
        allowed, _ = await check_rate_limit(key, max_requests, window)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many {action} attempts. Try again later.",
                headers={"Retry-After": str(window)},
            )
    except HTTPException:
        raise
    except Exception:
        pass  # Redis down - fail open


async def _check_account_lockout(user: User) -> None:
    """Check if the user's account is temporarily locked due to failed login attempts."""
    if user.locked_until:
        from datetime import UTC, datetime

        if datetime.now(UTC) < user.locked_until:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Account temporarily locked due to too many failed login attempts. Try again later.",
            )


async def _record_failed_login(db: AsyncSession, user: User) -> None:
    """Increment failed login counter; lock account after 10 consecutive failures."""
    from datetime import UTC, datetime, timedelta

    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= 10:
        user.locked_until = datetime.now(UTC) + timedelta(minutes=30)
        await log_auth_event(
            db,
            "auth.account_locked",
            user_id=user.id,
            details={
                "failed_attempts": user.failed_login_attempts,
                "locked_until": user.locked_until.isoformat(),
            },
        )
    await db.commit()


async def _clear_failed_logins(db: AsyncSession, user: User) -> None:
    """Reset failed login counter and record login time on successful login."""
    user.last_login_at = datetime.now(UTC)
    if user.failed_login_attempts and user.failed_login_attempts > 0:
        user.failed_login_attempts = 0
        user.locked_until = None
    await db.commit()


def _set_token_cookies(response: Response, tokens: Token) -> None:
    """Set httpOnly cookies for access and refresh tokens."""
    response.set_cookie(
        key="paws_access_token",
        value=tokens.access_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.access_token_expire_minutes * 60,
        path="/api",
    )
    response.set_cookie(
        key="paws_refresh_token",
        value=tokens.refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.refresh_token_expire_days * 86400,
        path="/api/auth/refresh",
    )
    # CSRF double-submit cookie (readable by JS, not httpOnly)
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        key="paws_csrf_token",
        value=csrf_token,
        httponly=False,
        secure=True,
        samesite="strict",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


def _make_tokens(user: User) -> Token:
    data = {"sub": str(user.id)}
    return Token(
        access_token=create_access_token(data),
        refresh_token=create_refresh_token(data),
    )


# --- Local Auth ---


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.local_auth_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local registration is disabled")

    await _check_auth_rate_limit(request, "register", settings.auth_register_limit_per_minute, 3600)

    # Validate password complexity
    password_error = validate_password(body.password)
    if password_error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=password_error)

    if await get_user_by_email(db, body.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    if await get_user_by_username(db, body.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    user = await create_local_user(db, body.email, body.username, body.password, body.full_name)
    await _create_personal_project(db, user)
    await _create_default_security_group(db, user)
    await _create_default_vpc(db, user)
    await _provision_pbs_namespace(user)
    client_ip = request.client.host if request.client else "unknown"
    await log_auth_event(db, "auth.register", user_id=user.id, details={"ip": client_ip, "username": user.username})
    return user


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    if not settings.local_auth_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local login is disabled")

    await _check_auth_rate_limit(request, "login", settings.auth_login_limit_per_minute, 900)

    client_ip = request.client.host if request.client else "unknown"

    # Find user first to check lockout
    user_check = await get_user_by_username(db, body.username)
    if user_check:
        await _check_account_lockout(user_check)

    user = await authenticate_local_user(db, body.username, body.password)
    if user is None:
        await log_auth_event(db, "auth.login_failed", details={"ip": client_ip, "username": body.username})
        if user_check:
            await _record_failed_login(db, user_check)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    await _clear_failed_logins(db, user)
    await log_auth_event(db, "auth.login_success", user_id=user.id, details={"ip": client_ip})

    tokens = _make_tokens(user)
    _set_token_cookies(response, tokens)
    # Also return tokens in body for clients that prefer Bearer header auth
    return {"access_token": tokens.access_token, "refresh_token": tokens.refresh_token, "token_type": "bearer"}


@router.post("/refresh")
async def refresh_token(
    request: Request, response: Response, refresh_token: str | None = None, db: AsyncSession = Depends(get_db)
):
    # Accept refresh token from body, query param, or cookie
    token = refresh_token or request.cookies.get("paws_refresh_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token provided")

    payload = decode_token(token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    # Check if refresh token is revoked
    jti = payload.get("jti")
    if jti:
        from app.core.security import is_token_revoked as _check_revoked

        if await _check_revoked(jti):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been revoked")

    import uuid

    from sqlalchemy import select

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Revoke old refresh token (rotation)
    if jti:
        await revoke_token(jti, 60)

    tokens = _make_tokens(user)
    _set_token_cookies(response, tokens)
    return {"access_token": tokens.access_token, "refresh_token": tokens.refresh_token, "token_type": "bearer"}


# --- Token Revocation ---


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current access token and clear cookies."""
    # Revoke access token via jti in Redis
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = decode_token(token)
        if payload and payload.get("jti"):
            remaining = int(payload.get("exp", 0) - __import__("time").time())
            if remaining > 0:
                await revoke_token(payload["jti"], remaining)

    # Revoke refresh token from cookie
    refresh_cookie = request.cookies.get("paws_refresh_token")
    if refresh_cookie:
        payload = decode_token(refresh_cookie)
        if payload and payload.get("jti"):
            remaining = int(payload.get("exp", 0) - __import__("time").time())
            if remaining > 0:
                await revoke_token(payload["jti"], remaining)

    # Clear cookies
    response.delete_cookie("paws_access_token", path="/api")
    response.delete_cookie("paws_refresh_token", path="/api/auth/refresh")
    response.delete_cookie("paws_csrf_token", path="/")

    await log_auth_event(db, "auth.logout", user_id=user.id)
    return {"status": "logged_out"}


@router.post("/revoke-all")
async def revoke_all_sessions(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke all sessions for the current user (force re-login everywhere)."""
    await revoke_all_user_tokens(str(user.id))
    await log_auth_event(db, "auth.revoke_all_sessions", user_id=user.id)
    return {"status": "all_sessions_revoked", "message": "All tokens issued before now are invalid"}


# --- OAuth / Authentik ---


@router.get("/oauth/login")
async def oauth_login(request: Request, redirect_uri: str):
    if not settings.oauth_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="OAuth login is disabled")

    await _check_auth_rate_limit(request, "oauth", 10, 60)

    state = secrets.token_urlsafe(32)
    # Store state in Redis with 5-minute expiry for CSRF protection
    try:
        from app.services.rate_limiter import get_redis

        r = await get_redis()
        await r.setex(f"oauth_state:{state}", 300, "1")
    except Exception:
        pass  # If Redis is down, state validation is skipped on callback
    auth_url = oauth_service.get_authorization_url(redirect_uri, state)
    return {"authorization_url": auth_url, "state": state}


@router.get("/oauth/callback")
async def oauth_callback(
    code: str, redirect_uri: str, response: Response, state: str = "", db: AsyncSession = Depends(get_db)
):
    if not settings.oauth_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="OAuth login is disabled")

    # Validate OAuth state to prevent CSRF
    if state:
        try:
            from app.services.rate_limiter import get_redis

            r = await get_redis()
            stored = await r.getdel(f"oauth_state:{state}")
            if stored is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state")
        except HTTPException:
            raise
        except Exception:
            pass  # If Redis is down, skip state validation

    try:
        token_data = await oauth_service.exchange_code(code, redirect_uri)
        userinfo = await oauth_service.get_userinfo(token_data["access_token"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to communicate with OAuth provider")

    oauth_sub = userinfo.get("sub")
    email = userinfo.get("email")
    username = userinfo.get("preferred_username", email.split("@")[0] if email else oauth_sub)
    full_name = userinfo.get("name")

    if not oauth_sub or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth provider did not return required fields",
        )

    # Check if user already exists
    user = await get_user_by_oauth_sub(db, oauth_sub)
    if user is None:
        # Check if email is already used by a local account
        existing = await get_user_by_email(db, email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already associated with a local account",
            )
        user = await create_oauth_user(db, email, username, oauth_sub, full_name)
        await _create_personal_project(db, user)
        await _create_default_security_group(db, user)
        await _create_default_vpc(db, user)
        await _provision_pbs_namespace(user)

    tokens = _make_tokens(user)
    _set_token_cookies(response, tokens)
    return {"access_token": tokens.access_token, "refresh_token": tokens.refresh_token, "token_type": "bearer"}


# --- Current User ---


@router.get("/me")
async def get_me(request: Request, user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)):
    from app.services.lifecycle_policy import get_effective_lifecycle

    lifecycle = await get_effective_lifecycle(db, user)
    data = {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "auth_provider": user.auth_provider,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "lifecycle_policy": lifecycle,
    }
    impersonator = getattr(request.state, "impersonated_by", None)
    if impersonator:
        data["impersonated_by"] = impersonator
    return data


# --- Helpers ---


async def _create_personal_project(db: AsyncSession, user: User) -> None:
    """Create a personal project for a new user."""
    project = Project(
        name=f"{user.username}'s Project",
        slug=f"personal-{user.username}",
        owner_id=user.id,
        is_personal=True,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.OWNER))
    await db.commit()


async def _create_default_security_group(db: AsyncSession, user: User) -> None:
    """Create a default security group with sensible rules for a new user."""
    sg = SecurityGroup(owner_id=user.id, name="default", description="Default security group")
    db.add(sg)
    await db.flush()
    # Allow all outbound
    db.add(
        SecurityGroupRule(
            security_group_id=sg.id,
            direction="egress",
            protocol="tcp",
            port_from=1,
            port_to=65535,
            cidr="0.0.0.0/0",
            description="Allow all outbound TCP",
        )
    )
    db.add(
        SecurityGroupRule(
            security_group_id=sg.id,
            direction="egress",
            protocol="udp",
            port_from=1,
            port_to=65535,
            cidr="0.0.0.0/0",
            description="Allow all outbound UDP",
        )
    )
    # Allow inbound SSH
    db.add(
        SecurityGroupRule(
            security_group_id=sg.id,
            direction="ingress",
            protocol="tcp",
            port_from=22,
            port_to=22,
            cidr="0.0.0.0/0",
            description="Allow SSH",
        )
    )
    # Allow inbound ICMP
    db.add(
        SecurityGroupRule(
            security_group_id=sg.id,
            direction="ingress",
            protocol="icmp",
            cidr="0.0.0.0/0",
            description="Allow ICMP (ping)",
        )
    )
    await db.commit()


async def _create_default_vpc(db: AsyncSession, user: User) -> None:
    """Create a default VPC with a default subnet for a new user."""
    from app.models.models import VPC, Subnet

    vpc = VPC(
        owner_id=user.id,
        name="default",
        cidr="10.0.0.0/16",
        is_default=True,
    )
    db.add(vpc)
    await db.flush()
    subnet = Subnet(
        vpc_id=vpc.id,
        name="default-subnet",
        cidr="10.0.1.0/24",
    )
    db.add(subnet)
    await db.commit()


async def _provision_pbs_namespace(user: User) -> None:
    """Create a PBS namespace for the user (best-effort, non-blocking)."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        from app.services.pbs_client import pbs_client

        namespace = f"user-{user.username}"
        pbs_client.create_namespace(namespace)
        logger.info("Created PBS namespace %s for user %s", namespace, user.id)
    except Exception as e:
        logger.warning("PBS namespace provisioning failed for %s: %s", user.username, e)

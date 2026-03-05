"""MFA (TOTP) setup, verification, and management endpoints."""

import base64
import hashlib
import io
import json
import secrets

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.core.pagination import MessageResponse
from app.models.models import User, UserMFA
from app.schemas.schemas import MFASetupResponse, MFAStatusResponse, MFAVerifyRequest

router = APIRouter(prefix="/api/mfa", tags=["mfa"])

BACKUP_CODE_COUNT = 10


def _generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> list[str]:
    """Generate plaintext backup codes (8 chars each)."""
    return [secrets.token_hex(4).upper() for _ in range(count)]


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


@router.get("/status", response_model=MFAStatusResponse)
async def mfa_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Check if MFA is enabled for the current user."""
    result = await db.execute(select(UserMFA).where(UserMFA.user_id == user.id))
    mfa = result.scalar_one_or_none()
    return MFAStatusResponse(
        is_enabled=mfa.is_enabled if mfa else False,
        has_totp=bool(mfa and mfa.totp_secret),
    )


@router.post("/setup", response_model=MFASetupResponse)
async def mfa_setup(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Generate a TOTP secret and QR code. Must be confirmed with /verify before activation."""
    result = await db.execute(select(UserMFA).where(UserMFA.user_id == user.id))
    mfa = result.scalar_one_or_none()

    if mfa and mfa.is_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is already enabled")

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name="PAWS")

    # Generate QR code as base64
    img = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # Generate backup codes
    backup_codes = _generate_backup_codes()
    hashed_codes = [_hash_code(c) for c in backup_codes]

    if mfa:
        mfa.totp_secret = secret
        mfa.backup_codes = json.dumps(hashed_codes)
        mfa.is_enabled = False
    else:
        mfa = UserMFA(
            user_id=user.id,
            totp_secret=secret,
            backup_codes=json.dumps(hashed_codes),
            is_enabled=False,
        )
        db.add(mfa)

    await db.commit()

    return MFASetupResponse(
        secret=secret,
        provisioning_uri=provisioning_uri,
        qr_code_base64=qr_b64,
        backup_codes=backup_codes,
    )


@router.post("/verify", response_model=MessageResponse)
async def mfa_verify(
    body: MFAVerifyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Verify a TOTP code to activate MFA. Called after /setup."""
    result = await db.execute(select(UserMFA).where(UserMFA.user_id == user.id))
    mfa = result.scalar_one_or_none()

    if not mfa or not mfa.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA setup not initiated")

    if mfa.is_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is already enabled")

    totp = pyotp.TOTP(mfa.totp_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    mfa.is_enabled = True
    await db.commit()
    return MessageResponse(status="ok", message="MFA enabled successfully")


@router.post("/disable", response_model=MessageResponse)
async def mfa_disable(
    body: MFAVerifyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Disable MFA. Requires a valid TOTP code or backup code."""
    result = await db.execute(select(UserMFA).where(UserMFA.user_id == user.id))
    mfa = result.scalar_one_or_none()

    if not mfa or not mfa.is_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")

    # Try TOTP first
    totp = pyotp.TOTP(mfa.totp_secret)
    code_valid = totp.verify(body.code, valid_window=1)

    # Try backup code
    if not code_valid:
        code_valid = _consume_backup_code(mfa, body.code)

    if not code_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

    mfa.is_enabled = False
    mfa.totp_secret = None
    mfa.backup_codes = None
    await db.commit()
    return MessageResponse(status="ok", message="MFA disabled successfully")


@router.post("/regenerate-backup-codes", response_model=MFASetupResponse)
async def regenerate_backup_codes(
    body: MFAVerifyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Regenerate backup codes. Requires a valid TOTP code."""
    result = await db.execute(select(UserMFA).where(UserMFA.user_id == user.id))
    mfa = result.scalar_one_or_none()

    if not mfa or not mfa.is_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")

    totp = pyotp.TOTP(mfa.totp_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    backup_codes = _generate_backup_codes()
    hashed_codes = [_hash_code(c) for c in backup_codes]
    mfa.backup_codes = json.dumps(hashed_codes)
    await db.commit()

    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name="PAWS")
    img = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return MFASetupResponse(
        secret=mfa.totp_secret,
        provisioning_uri=provisioning_uri,
        qr_code_base64=qr_b64,
        backup_codes=backup_codes,
    )


def _consume_backup_code(mfa: UserMFA, code: str) -> bool:
    """Check and consume a backup code. Returns True if valid."""
    if not mfa.backup_codes:
        return False
    hashed = _hash_code(code)
    codes: list[str] = json.loads(mfa.backup_codes)
    if hashed in codes:
        codes.remove(hashed)
        mfa.backup_codes = json.dumps(codes)
        return True
    return False


def verify_mfa_code(mfa: UserMFA, code: str) -> bool:
    """Verify a TOTP or backup code during login. Used by auth router."""
    totp = pyotp.TOTP(mfa.totp_secret)
    if totp.verify(code, valid_window=1):
        return True
    return _consume_backup_code(mfa, code)

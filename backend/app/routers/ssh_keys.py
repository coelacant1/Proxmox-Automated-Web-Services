"""SSH key pair management for users."""

import base64
import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import SSHKeyPair, User
from app.schemas.schemas import SSHKeyCreate, SSHKeyRead

router = APIRouter(prefix="/api/ssh-keys", tags=["ssh-keys"])

MAX_KEYS_PER_USER = 20
SSH_KEY_PATTERN = re.compile(r"^(ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp\d+|ssh-dss)\s+\S+")


def _compute_fingerprint(public_key: str) -> str:
    """Compute MD5 fingerprint from an SSH public key."""
    parts = public_key.strip().split()
    if len(parts) < 2:
        raise ValueError("Invalid SSH key format")
    key_data = base64.b64decode(parts[1])
    digest = hashlib.md5(key_data).hexdigest()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


@router.get("/", response_model=list[SSHKeyRead])
async def list_ssh_keys(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(SSHKeyPair).where(SSHKeyPair.owner_id == user.id).order_by(SSHKeyPair.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/", response_model=SSHKeyRead, status_code=status.HTTP_201_CREATED)
async def create_ssh_key(
    body: SSHKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    # Validate key format
    if not SSH_KEY_PATTERN.match(body.public_key.strip()):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid SSH public key format")

    # Check limit
    count_result = await db.execute(
        select(func.count()).select_from(SSHKeyPair).where(SSHKeyPair.owner_id == user.id)
    )
    if (count_result.scalar() or 0) >= MAX_KEYS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum of {MAX_KEYS_PER_USER} SSH keys per user",
        )

    # Check duplicate name
    existing = await db.execute(
        select(SSHKeyPair).where(SSHKeyPair.owner_id == user.id, SSHKeyPair.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SSH key name already exists")

    try:
        fingerprint = _compute_fingerprint(body.public_key)
    except Exception:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Could not parse SSH public key")

    key = SSHKeyPair(owner_id=user.id, name=body.name, public_key=body.public_key.strip(), fingerprint=fingerprint)
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ssh_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(SSHKeyPair).where(SSHKeyPair.id == key_id, SSHKeyPair.owner_id == user.id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSH key not found")

    await db.delete(key)
    await db.commit()

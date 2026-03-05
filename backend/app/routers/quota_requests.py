"""User-facing quota request endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.core.pagination import PaginatedParams, PaginatedResponse
from app.models.models import QuotaRequest, User, UserQuota
from app.schemas.schemas import QuotaRequestCreate, QuotaRequestRead

router = APIRouter(prefix="/api/quota-requests", tags=["quota-requests"])

VALID_QUOTA_FIELDS = {"max_vms", "max_containers", "max_vcpus", "max_ram_mb", "max_disk_gb", "max_snapshots"}


@router.get("/", response_model=PaginatedResponse[QuotaRequestRead])
async def list_my_quota_requests(
    params: PaginatedParams = Depends(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List current user's quota requests."""
    base = select(QuotaRequest).where(QuotaRequest.user_id == user.id)

    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0

    result = await db.execute(
        base.order_by(QuotaRequest.created_at.desc()).offset(params.offset).limit(params.per_page)
    )
    return PaginatedResponse.create(list(result.scalars().all()), total, params)


@router.post("/", response_model=QuotaRequestRead, status_code=status.HTTP_201_CREATED)
async def submit_quota_request(
    data: QuotaRequestCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Submit a quota increase request."""
    if data.request_type not in VALID_QUOTA_FIELDS:
        raise HTTPException(status_code=400, detail=f"Invalid request_type. Must be one of: {VALID_QUOTA_FIELDS}")

    # Check for existing pending request of same type
    existing = await db.execute(
        select(QuotaRequest).where(
            QuotaRequest.user_id == user.id,
            QuotaRequest.request_type == data.request_type,
            QuotaRequest.status == "pending",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="You already have a pending request for this quota type")

    # Get current quota value
    quota_result = await db.execute(select(UserQuota).where(UserQuota.user_id == user.id))
    quota = quota_result.scalar_one_or_none()
    if not quota:
        raise HTTPException(status_code=404, detail="User quota not found")

    current_value = getattr(quota, data.request_type, 0)

    if data.requested_value <= current_value:
        raise HTTPException(status_code=400, detail="Requested value must be greater than current value")

    qr = QuotaRequest(
        user_id=user.id,
        request_type=data.request_type,
        current_value=current_value,
        requested_value=data.requested_value,
        reason=data.reason,
    )
    db.add(qr)
    await db.commit()
    await db.refresh(qr)
    return qr

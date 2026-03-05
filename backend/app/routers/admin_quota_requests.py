"""Admin quota request management endpoints."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.core.pagination import PaginatedParams, PaginatedResponse
from app.models.models import QuotaRequest, User, UserQuota
from app.schemas.schemas import QuotaRequestRead, QuotaRequestReview

router = APIRouter(prefix="/api/admin/quota-requests", tags=["admin"])


@router.get("/", response_model=PaginatedResponse[QuotaRequestRead])
async def list_all_quota_requests(
    status_filter: str | None = Query(None, pattern="^(pending|approved|denied)$"),
    params: PaginatedParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all quota requests, optionally filtered by status."""
    base = select(QuotaRequest)
    if status_filter:
        base = base.where(QuotaRequest.status == status_filter)

    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0

    query = base.order_by(QuotaRequest.created_at.desc()).offset(params.offset).limit(params.per_page)
    result = await db.execute(query)
    return PaginatedResponse.create(list(result.scalars().all()), total, params)


@router.get("/pending/count")
async def pending_count(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    from sqlalchemy import func

    result = await db.execute(select(func.count(QuotaRequest.id)).where(QuotaRequest.status == "pending"))
    return {"count": result.scalar()}


@router.patch("/{request_id}", response_model=QuotaRequestRead)
async def review_quota_request(
    request_id: str,
    review: QuotaRequestReview,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Approve or deny a quota request. On approval, the user's quota is updated automatically."""
    result = await db.execute(select(QuotaRequest).where(QuotaRequest.id == uuid.UUID(request_id)))
    qr = result.scalar_one_or_none()
    if not qr:
        raise HTTPException(status_code=404, detail="Quota request not found")
    if qr.status != "pending":
        raise HTTPException(status_code=400, detail="Request already reviewed")
    if review.status not in ("approved", "denied"):
        raise HTTPException(status_code=400, detail="Status must be 'approved' or 'denied'")

    qr.status = review.status
    qr.admin_notes = review.admin_notes
    qr.reviewed_by = admin.id
    qr.reviewed_at = datetime.now(UTC)

    # Auto-apply quota on approval
    if review.status == "approved":
        quota_result = await db.execute(select(UserQuota).where(UserQuota.user_id == qr.user_id))
        quota = quota_result.scalar_one_or_none()
        if quota and hasattr(quota, qr.request_type):
            setattr(quota, qr.request_type, qr.requested_value)

    await db.commit()
    await db.refresh(qr)
    return qr

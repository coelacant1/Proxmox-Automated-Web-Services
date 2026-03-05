"""Internal DNS record management for VPC service discovery."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import DNSRecord, User

router = APIRouter(prefix="/api/dns", tags=["dns"])

VALID_RECORD_TYPES = {"A", "AAAA", "CNAME", "SRV", "TXT"}
MAX_DNS_RECORDS_PER_USER = 50


class DNSRecordCreate(BaseModel):
    record_type: str
    name: str
    value: str
    ttl: int = 300
    vpc_id: str | None = None

    @field_validator("record_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        v = v.upper()
        if v not in VALID_RECORD_TYPES:
            raise ValueError(f"Record type must be one of: {', '.join(sorted(VALID_RECORD_TYPES))}")
        return v

    @field_validator("ttl")
    @classmethod
    def validate_ttl(cls, v: int) -> int:
        if v < 60 or v > 86400:
            raise ValueError("TTL must be 60-86400 seconds")
        return v


class DNSRecordUpdate(BaseModel):
    value: str | None = None
    ttl: int | None = None


@router.get("")
async def list_dns_records(
    vpc_id: str | None = None,
    record_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    query = select(DNSRecord).where(DNSRecord.owner_id == user.id)
    if vpc_id:
        query = query.where(DNSRecord.vpc_id == uuid.UUID(vpc_id))
    if record_type:
        query = query.where(DNSRecord.record_type == record_type.upper())
    query = query.order_by(DNSRecord.name)

    result = await db.execute(query)
    records = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "record_type": r.record_type,
            "name": r.name,
            "value": r.value,
            "ttl": r.ttl,
            "vpc_id": str(r.vpc_id) if r.vpc_id else None,
            "created_at": str(r.created_at),
        }
        for r in records
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_dns_record(
    body: DNSRecordCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    # Quota check
    count_result = await db.execute(
        select(func.count(DNSRecord.id)).where(DNSRecord.owner_id == user.id)
    )
    if (count_result.scalar() or 0) >= MAX_DNS_RECORDS_PER_USER:
        raise HTTPException(status_code=403, detail=f"DNS record quota exceeded ({MAX_DNS_RECORDS_PER_USER} max)")

    record = DNSRecord(
        owner_id=user.id,
        record_type=body.record_type,
        name=body.name,
        value=body.value,
        ttl=body.ttl,
        vpc_id=uuid.UUID(body.vpc_id) if body.vpc_id else None,
    )
    db.add(record)
    await db.commit()

    return {
        "id": str(record.id),
        "record_type": record.record_type,
        "name": record.name,
        "value": record.value,
        "ttl": record.ttl,
    }


@router.patch("/{record_id}")
async def update_dns_record(
    record_id: str,
    body: DNSRecordUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    record = await _get_user_record(db, user.id, record_id)
    if body.value is not None:
        record.value = body.value
    if body.ttl is not None:
        if body.ttl < 60 or body.ttl > 86400:
            raise HTTPException(status_code=422, detail="TTL must be 60-86400 seconds")
        record.ttl = body.ttl
    await db.commit()
    return {"status": "updated"}


@router.delete("/{record_id}")
async def delete_dns_record(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    record = await _get_user_record(db, user.id, record_id)
    await db.delete(record)
    await db.commit()
    return {"status": "deleted"}


async def _get_user_record(db: AsyncSession, user_id: uuid.UUID, record_id: str) -> DNSRecord:
    result = await db.execute(
        select(DNSRecord).where(DNSRecord.id == uuid.UUID(record_id), DNSRecord.owner_id == user_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="DNS record not found")
    return record

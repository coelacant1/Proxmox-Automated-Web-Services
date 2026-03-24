"""Instance type management - admin CRUD + user listing."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import InstanceType
from app.schemas.schemas import InstanceTypeCreate, InstanceTypeRead, InstanceTypeUpdate

router = APIRouter(prefix="/api/instance-types", tags=["instance-types"])


@router.get("/", response_model=list[InstanceTypeRead])
async def list_instance_types(
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(get_current_active_user),
):
    """List active instance types (user-facing)."""
    q = (
        select(InstanceType)
        .where(InstanceType.is_active.is_(True))
        .order_by(InstanceType.category, InstanceType.sort_order, InstanceType.vcpus)
    )
    if category:
        q = q.where(InstanceType.category == category)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/", response_model=InstanceTypeRead, status_code=status.HTTP_201_CREATED)
async def create_instance_type(
    body: InstanceTypeCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Create a new instance type (admin only)."""
    existing = await db.execute(select(InstanceType).where(InstanceType.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Instance type name already exists")

    instance_type = InstanceType(**body.model_dump())
    db.add(instance_type)
    await db.commit()
    await db.refresh(instance_type)
    return instance_type


@router.patch("/{instance_type_id}", response_model=InstanceTypeRead)
async def update_instance_type(
    instance_type_id: str,
    body: InstanceTypeUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Update an instance type (admin only)."""
    result = await db.execute(select(InstanceType).where(InstanceType.id == instance_type_id))
    it = result.scalar_one_or_none()
    if not it:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance type not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(it, field, value)
    await db.commit()
    await db.refresh(it)
    return it


@router.delete("/{instance_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instance_type(
    instance_type_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Delete an instance type (admin only)."""
    result = await db.execute(select(InstanceType).where(InstanceType.id == instance_type_id))
    it = result.scalar_one_or_none()
    if not it:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance type not found")

    await db.delete(it)
    await db.commit()

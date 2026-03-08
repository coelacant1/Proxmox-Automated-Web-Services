"""VPC and subnet management API."""

import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import VPC, Subnet, User
from app.schemas.schemas import SubnetCreate, SubnetRead, VPCCreate, VPCRead
from app.services.group_access import check_group_access

router = APIRouter(prefix="/api/vpcs", tags=["vpcs"])


async def _get_vpc(
    db: AsyncSession, user_id: _uuid.UUID, vpc_id: str, min_perm: str = "read",
) -> VPC:
    """Get a VPC by ownership or group share."""
    vid = _uuid.UUID(vpc_id)
    result = await db.execute(
        select(VPC).where(VPC.id == vid, VPC.owner_id == user_id).options(selectinload(VPC.subnets))
    )
    vpc = result.scalar_one_or_none()
    if not vpc:
        res2 = await db.execute(select(VPC).where(VPC.id == vid).options(selectinload(VPC.subnets)))
        vpc = res2.scalar_one_or_none()
        if vpc and not await check_group_access(db, user_id, "vpc", vid, min_perm):
            vpc = None
    if not vpc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VPC not found")
    return vpc


@router.get("/", response_model=list[VPCRead])
async def list_vpcs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(VPC)
        .where(VPC.owner_id == user.id)
        .options(selectinload(VPC.subnets))
        .order_by(VPC.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/", response_model=VPCRead, status_code=status.HTTP_201_CREATED)
async def create_vpc(
    body: VPCCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    existing = await db.execute(select(VPC).where(VPC.owner_id == user.id, VPC.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="VPC name already exists")

    vpc = VPC(
        owner_id=user.id,
        name=body.name,
        cidr=body.cidr,
        gateway=body.gateway,
        dhcp_enabled=body.dhcp_enabled,
    )
    db.add(vpc)
    await db.commit()

    result = await db.execute(
        select(VPC).where(VPC.id == vpc.id).options(selectinload(VPC.subnets))
    )
    return result.scalar_one()


@router.get("/{vpc_id}", response_model=VPCRead)
async def get_vpc(
    vpc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    return await _get_vpc(db, user.id, vpc_id)


@router.delete("/{vpc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vpc(
    vpc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vpc = await _get_vpc(db, user.id, vpc_id, min_perm="admin")
    if vpc.is_default:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete default VPC")

    await db.delete(vpc)
    await db.commit()


# --- Subnets ---


@router.post("/{vpc_id}/subnets", response_model=SubnetRead, status_code=status.HTTP_201_CREATED)
async def create_subnet(
    vpc_id: str,
    body: SubnetCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    vpc = await _get_vpc(db, user.id, vpc_id, min_perm="admin")

    subnet = Subnet(vpc_id=vpc.id, name=body.name, cidr=body.cidr, gateway=body.gateway, is_public=body.is_public)
    db.add(subnet)
    await db.commit()
    await db.refresh(subnet)
    return subnet


@router.delete("/{vpc_id}/subnets/{subnet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subnet(
    vpc_id: str,
    subnet_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await _get_vpc(db, user.id, vpc_id, min_perm="admin")

    subnet_result = await db.execute(
        select(Subnet).where(Subnet.id == subnet_id, Subnet.vpc_id == vpc_id)
    )
    subnet = subnet_result.scalar_one_or_none()
    if not subnet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subnet not found")

    await db.delete(subnet)
    await db.commit()


@router.get("/{vpc_id}/instances")
async def list_vpc_instances(
    vpc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List resources attached to a VPC."""
    import json
    import uuid

    from app.models.models import Resource

    # Verify VPC ownership
    vpc_result = await db.execute(
        select(VPC).where(VPC.id == uuid.UUID(vpc_id), VPC.owner_id == user.id)
    )
    if not vpc_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="VPC not found")

    # Find resources with this vpc_id in specs
    result = await db.execute(
        select(Resource).where(Resource.owner_id == user.id)
    )
    instances = []
    for r in result.scalars().all():
        specs = r.specs
        if isinstance(specs, str):
            try:
                specs = json.loads(specs)
            except (json.JSONDecodeError, TypeError):
                specs = {}
        if isinstance(specs, dict) and specs.get("vpc_id") == vpc_id:
            instances.append({
                "id": str(r.id),
                "name": r.display_name,
                "type": r.resource_type,
                "status": r.status,
            })
    return instances

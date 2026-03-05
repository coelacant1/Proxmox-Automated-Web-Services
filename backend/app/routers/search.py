"""Global search API - cross-resource search for resources, templates, buckets."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import Resource, TemplateCatalog, User

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/")
async def global_search(
    q: str = Query(..., min_length=1, max_length=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Search across resources, templates, and buckets."""
    results: dict[str, list] = {"resources": [], "templates": [], "buckets": []}
    pattern = f"%{q}%"

    # Search user resources
    res = await db.execute(
        select(Resource)
        .where(Resource.owner_id == user.id, Resource.display_name.ilike(pattern))
        .limit(10)
    )
    for r in res.scalars().all():
        results["resources"].append({
            "id": str(r.id),
            "name": r.display_name,
            "type": r.resource_type,
            "status": r.status,
        })

    # Search templates
    res = await db.execute(
        select(TemplateCatalog)
        .where(TemplateCatalog.is_active.is_(True), TemplateCatalog.name.ilike(pattern))
        .limit(10)
    )
    for t in res.scalars().all():
        results["templates"].append({
            "id": str(t.id),
            "name": t.name,
            "os_type": t.os_type,
            "category": t.category,
        })

    # Search buckets (resources of type 'bucket')
    res = await db.execute(
        select(Resource)
        .where(
            Resource.owner_id == user.id,
            Resource.resource_type == "bucket",
            Resource.display_name.ilike(pattern),
        )
        .limit(10)
    )
    for b in res.scalars().all():
        results["buckets"].append({
            "id": str(b.id),
            "name": b.display_name,
            "status": b.status,
        })

    total = sum(len(v) for v in results.values())
    return {"query": q, "total": total, "results": results}

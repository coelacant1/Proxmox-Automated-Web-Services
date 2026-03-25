"""Documentation pages - user-created markdown docs with sharing."""

import re
import uuid
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.models import DocPage, User, UserGroupMember
from app.services.audit_service import log_action

router = APIRouter(prefix="/api/docs", tags=["docs"])

LOCK_TIMEOUT_MINUTES = 15


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:200] or "untitled"


class DocPageCreate(BaseModel):
    title: str
    content: str = ""
    visibility: str = "private"
    group_id: str | None = None


class DocPageUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    visibility: str | None = None
    group_id: str | None = None


class DocPageRead(BaseModel):
    id: str
    owner_id: str
    owner_username: str
    title: str
    slug: str
    content: str
    visibility: str
    group_id: str | None
    group_name: str | None
    locked_by: str | None
    locked_at: str | None
    created_at: str
    updated_at: str


def _serialize(doc: DocPage) -> dict:
    return {
        "id": str(doc.id),
        "owner_id": str(doc.owner_id),
        "owner_username": doc.owner.username if doc.owner else "unknown",
        "title": doc.title,
        "slug": doc.slug,
        "content": doc.content,
        "visibility": doc.visibility,
        "group_id": str(doc.group_id) if doc.group_id else None,
        "group_name": doc.group.name if doc.group else None,
        "locked_by": str(doc.locked_by) if doc.locked_by else None,
        "locked_at": str(doc.locked_at) if doc.locked_at else None,
        "created_at": str(doc.created_at),
        "updated_at": str(doc.updated_at),
    }


async def _visible_docs_query(user: User, db: AsyncSession):
    """Build query for docs the user can see."""
    # Get user's group IDs
    grp_result = await db.execute(select(UserGroupMember.group_id).where(UserGroupMember.user_id == user.id))
    group_ids = [row[0] for row in grp_result.all()]

    q = select(DocPage).where(
        or_(
            DocPage.owner_id == user.id,
            DocPage.visibility == "public",
            (DocPage.visibility == "group" if not group_ids else DocPage.visibility == "group")
            & DocPage.group_id.in_(group_ids)
            if group_ids
            else DocPage.id == None,  # noqa: E711
        )
    )
    return q


@router.get("/")
async def list_docs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List all documentation pages visible to the current user."""
    grp_result = await db.execute(select(UserGroupMember.group_id).where(UserGroupMember.user_id == user.id))
    group_ids = [row[0] for row in grp_result.all()]

    conditions = [
        DocPage.owner_id == user.id,
        DocPage.visibility == "public",
    ]
    if group_ids:
        conditions.append((DocPage.visibility == "group") & DocPage.group_id.in_(group_ids))

    q = select(DocPage).where(or_(*conditions)).order_by(DocPage.updated_at.desc())
    result = await db.execute(q)
    docs = result.scalars().all()

    if user.role == "admin":
        q_all = select(DocPage).order_by(DocPage.updated_at.desc())
        result = await db.execute(q_all)
        docs = result.scalars().all()

    return [_serialize(d) for d in docs]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_doc(
    body: DocPageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Create a new documentation page."""
    if body.visibility not in ("private", "group", "public"):
        raise HTTPException(status_code=422, detail="visibility must be private, group, or public")

    if body.visibility == "group" and not body.group_id:
        raise HTTPException(status_code=422, detail="group_id required for group visibility")

    slug = _slugify(body.title)
    existing = await db.execute(select(DocPage).where(DocPage.owner_id == user.id, DocPage.slug == slug))
    if existing.scalar_one_or_none():
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    doc = DocPage(
        owner_id=user.id,
        title=body.title.strip(),
        slug=slug,
        content=body.content,
        visibility=body.visibility,
        group_id=uuid.UUID(body.group_id) if body.group_id else None,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    await log_action(db, user.id, "doc_create", "docs", details={"title": doc.title})
    return _serialize(doc)


@router.get("/{doc_id}")
async def get_doc(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get a single documentation page."""
    result = await db.execute(select(DocPage).where(DocPage.id == uuid.UUID(doc_id)))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Doc page not found")

    if not await _can_view(doc, user, db):
        raise HTTPException(status_code=403, detail="Access denied")

    return _serialize(doc)


@router.patch("/{doc_id}")
async def update_doc(
    doc_id: str,
    body: DocPageUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Update a documentation page. Only the owner (or admin) can edit."""
    result = await db.execute(select(DocPage).where(DocPage.id == uuid.UUID(doc_id)))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Doc page not found")

    if doc.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the owner can edit")

    # Check edit lock
    if doc.locked_by and doc.locked_by != user.id:
        from datetime import datetime

        if doc.locked_at and (datetime.now(UTC) - doc.locked_at).total_seconds() < LOCK_TIMEOUT_MINUTES * 60:
            raise HTTPException(status_code=409, detail="Document is being edited by another user")

    if body.title is not None:
        doc.title = body.title.strip()
        doc.slug = _slugify(body.title)
    if body.content is not None:
        doc.content = body.content
    if body.visibility is not None:
        if body.visibility not in ("private", "group", "public"):
            raise HTTPException(status_code=422, detail="visibility must be private, group, or public")
        doc.visibility = body.visibility
    if body.group_id is not None:
        doc.group_id = uuid.UUID(body.group_id) if body.group_id else None

    await db.commit()
    await db.refresh(doc)
    await log_action(db, user.id, "doc_update", "docs", details={"title": doc.title})
    return _serialize(doc)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doc(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Delete a documentation page."""
    result = await db.execute(select(DocPage).where(DocPage.id == uuid.UUID(doc_id)))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Doc page not found")

    if doc.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the owner can delete")

    await log_action(db, user.id, "doc_delete", "docs", details={"title": doc.title})
    await db.delete(doc)
    await db.commit()


@router.post("/{doc_id}/lock")
async def lock_doc(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Acquire an edit lock on a doc page."""
    from datetime import datetime

    result = await db.execute(select(DocPage).where(DocPage.id == uuid.UUID(doc_id)))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Doc page not found")

    if doc.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the owner can edit")

    # Check if someone else holds a fresh lock
    if doc.locked_by and doc.locked_by != user.id:
        if doc.locked_at and (datetime.now(UTC) - doc.locked_at).total_seconds() < LOCK_TIMEOUT_MINUTES * 60:
            raise HTTPException(status_code=409, detail="Document is locked by another user")

    doc.locked_by = user.id
    doc.locked_at = datetime.now(UTC)
    await db.commit()
    return {"locked": True}


@router.post("/{doc_id}/unlock")
async def unlock_doc(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Release an edit lock on a doc page."""
    result = await db.execute(select(DocPage).where(DocPage.id == uuid.UUID(doc_id)))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Doc page not found")

    if doc.locked_by != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not your lock")

    doc.locked_by = None
    doc.locked_at = None
    await db.commit()
    return {"locked": False}


async def _can_view(doc: DocPage, user: User, db: AsyncSession) -> bool:
    if user.role == "admin":
        return True
    if doc.owner_id == user.id:
        return True
    if doc.visibility == "public":
        return True
    if doc.visibility == "group" and doc.group_id:
        grp_result = await db.execute(
            select(UserGroupMember.id).where(
                UserGroupMember.group_id == doc.group_id,
                UserGroupMember.user_id == user.id,
            )
        )
        return grp_result.scalar_one_or_none() is not None
    return False

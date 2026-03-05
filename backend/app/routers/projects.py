"""Project management API - create, list, update projects and manage members."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.core.pagination import PaginatedParams, PaginatedResponse
from app.models.models import Project, ProjectMember, ProjectRole, User
from app.schemas.schemas import (
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberRead,
    ProjectRead,
    ProjectUpdate,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80]


@router.get("/", response_model=PaginatedResponse[ProjectRead])
async def list_projects(
    pagination: PaginatedParams = Depends(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List projects the current user is a member of."""
    member_q = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    base = select(Project).where(
        (Project.owner_id == user.id) | (Project.id.in_(member_q))
    )
    count_q = select(Project.id).where(
        (Project.owner_id == user.id) | (Project.id.in_(member_q))
    )
    total_result = await db.execute(count_q)
    total = len(total_result.all())

    result = await db.execute(
        base.order_by(Project.created_at.desc())
        .offset((pagination.page - 1) * pagination.per_page)
        .limit(pagination.per_page)
    )
    projects = result.scalars().all()
    return PaginatedResponse.create(projects, total, pagination)


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    slug = slugify(body.name)
    existing = await db.execute(select(Project).where(Project.slug == slug))
    if existing.scalar_one_or_none():
        # Append a short suffix
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    project = Project(
        name=body.name,
        slug=slug,
        description=body.description,
        owner_id=user.id,
    )
    db.add(project)
    await db.flush()
    # Add owner as member with owner role
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.OWNER))
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    project = await _get_project_with_access(project_id, user, db)
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    project = await _get_project_with_access(project_id, user, db, min_role=ProjectRole.ADMIN)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    project = await _get_project_with_access(project_id, user, db, min_role=ProjectRole.OWNER)
    if project.is_personal:
        raise HTTPException(status_code=400, detail="Cannot delete personal project")
    await db.delete(project)
    await db.commit()


# --- Members ---


@router.get("/{project_id}/members", response_model=list[ProjectMemberRead])
async def list_members(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await _get_project_with_access(project_id, user, db)
    result = await db.execute(
        select(ProjectMember).where(ProjectMember.project_id == project_id)
    )
    return result.scalars().all()


@router.post("/{project_id}/members", response_model=ProjectMemberRead, status_code=status.HTTP_201_CREATED)
async def add_member(
    project_id: uuid.UUID,
    body: ProjectMemberAdd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await _get_project_with_access(project_id, user, db, min_role=ProjectRole.ADMIN)
    # Check user exists
    target = await db.execute(select(User).where(User.id == body.user_id))
    if not target.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")
    # Check not already member
    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == body.user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member")
    member = ProjectMember(project_id=project_id, user_id=body.user_id, role=body.role)
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await _get_project_with_access(project_id, user, db, min_role=ProjectRole.ADMIN)
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.role != ProjectRole.OWNER,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found or cannot remove owner")
    await db.delete(member)
    await db.commit()


# --- Helpers ---

_ROLE_HIERARCHY = {
    ProjectRole.OWNER: 0,
    ProjectRole.ADMIN: 1,
    ProjectRole.MEMBER: 2,
    ProjectRole.VIEWER: 3,
}


async def _get_project_with_access(
    project_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: str | None = None,
) -> Project:
    result = await db.execute(
        select(Project).options(selectinload(Project.members)).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Platform admins can access any project
    if user.is_superuser or user.role == "admin":
        return project

    membership = next((m for m in project.members if m.user_id == user.id), None)
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this project")

    if min_role and _ROLE_HIERARCHY.get(membership.role, 99) > _ROLE_HIERARCHY.get(min_role, 99):
        raise HTTPException(status_code=403, detail="Insufficient project permissions")

    return project

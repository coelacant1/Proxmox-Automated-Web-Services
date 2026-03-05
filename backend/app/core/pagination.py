"""Standardized pagination, filtering, and response models for all API endpoints."""

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PaginatedParams:
    """Dependency for standardized pagination across all list endpoints."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number (1-indexed)"),
        per_page: int = Query(50, ge=1, le=100, description="Items per page (max 100)"),
    ):
        self.page = page
        self.per_page = per_page
        self.offset = (page - 1) * per_page


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard envelope for all paginated list endpoints."""

    items: list[T]
    total: int
    page: int
    per_page: int
    pages: int

    @classmethod
    def create(cls, items: list[T], total: int, params: PaginatedParams) -> "PaginatedResponse[T]":
        return cls(
            items=items,
            total=total,
            page=params.page,
            per_page=params.per_page,
            pages=max(1, (total + params.per_page - 1) // params.per_page),
        )


class MessageResponse(BaseModel):
    """Standard response for actions that return a status message."""

    status: str
    message: str | None = None
    detail: dict | None = None


class TaskResponse(BaseModel):
    """Standard response for async Proxmox tasks."""

    status: str
    task_id: str | None = None
    resource_id: str | None = None
    message: str | None = None

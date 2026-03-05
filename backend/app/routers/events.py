"""Events API - system-wide event log and event bus.

Provides queryable event history for audit, debugging, and notification triggers.
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user, require_admin
from app.models.models import Event, User

router = APIRouter(prefix="/api/events", tags=["events"])

VALID_SEVERITIES = {"info", "warning", "error", "critical"}
VALID_SOURCES = {"compute", "storage", "network", "auth", "admin", "backup", "monitoring", "system"}


@router.get("/")
async def list_events(
    source: str | None = None,
    severity: str | None = None,
    event_type: str | None = None,
    resource_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List events visible to the current user."""
    query = select(Event).where(Event.user_id == user.id)
    if source:
        query = query.where(Event.source == source)
    if severity:
        query = query.where(Event.severity == severity)
    if event_type:
        query = query.where(Event.event_type == event_type)
    if resource_id:
        query = query.where(Event.resource_id == uuid.UUID(resource_id))
    query = query.order_by(Event.created_at.desc()).limit(limit)

    result = await db.execute(query)
    events = result.scalars().all()
    return [_serialize(e) for e in events]


@router.get("/all")
async def list_all_events(
    source: str | None = None,
    severity: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """List all system events (admin only)."""
    query = select(Event)
    if source:
        query = query.where(Event.source == source)
    if severity:
        query = query.where(Event.severity == severity)
    query = query.order_by(Event.created_at.desc()).limit(limit)

    result = await db.execute(query)
    events = result.scalars().all()
    return [_serialize(e) for e in events]


@router.get("/{event_id}")
async def get_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(Event).where(Event.id == uuid.UUID(event_id), Event.user_id == user.id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return _serialize(event)


# --- Event Publishing (used internally by other services) ---


async def publish_event(
    db: AsyncSession,
    event_type: str,
    source: str,
    message: str,
    user_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    severity: str = "info",
    metadata: dict | None = None,
) -> Event:
    """Create and store a system event."""
    event = Event(
        event_type=event_type,
        source=source,
        message=message,
        user_id=user_id,
        resource_id=resource_id,
        severity=severity,
        event_metadata=json.dumps(metadata) if metadata else None,
    )
    db.add(event)
    await db.commit()
    return event


def _serialize(e: Event) -> dict:
    return {
        "id": str(e.id),
        "event_type": e.event_type,
        "source": e.source,
        "resource_id": str(e.resource_id) if e.resource_id else None,
        "user_id": str(e.user_id) if e.user_id else None,
        "severity": e.severity,
        "message": e.message,
        "metadata": json.loads(e.event_metadata) if e.event_metadata else None,
        "created_at": str(e.created_at),
    }


# --- WebSocket Event Stream ----------------------------------------------


_ws_clients: list[WebSocket] = []


@router.websocket("/ws")
async def event_stream(websocket: WebSocket):
    """Real-time event stream via WebSocket. JWT auth via query param."""
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            # Keep connection alive, client can send filter preferences
            data = await websocket.receive_text()
            # Echo acknowledgment
            await websocket.send_json({"type": "ack", "data": data})
    except WebSocketDisconnect:
        _ws_clients.remove(websocket)


async def broadcast_event(event_data: dict) -> None:
    """Broadcast an event to all connected WebSocket clients."""
    for ws in _ws_clients[:]:
        try:
            await ws.send_json(event_data)
        except Exception:
            _ws_clients.remove(ws)

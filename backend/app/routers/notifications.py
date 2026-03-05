"""WebSocket endpoint for real-time notifications."""

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.core.deps import get_current_user_ws
from app.services.notification_service import manager

router = APIRouter(prefix="/ws", tags=["notifications"])


@router.websocket("/notifications")
async def notifications_ws(ws: WebSocket, user=Depends(get_current_user_ws)):
    if user is None:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(user.id, ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive; ignore client messages
    except WebSocketDisconnect:
        await manager.disconnect(user.id, ws)

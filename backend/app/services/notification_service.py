"""WebSocket notification manager for real-time updates."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import WebSocket


class ConnectionManager:
    """Manages per-user WebSocket connections for real-time notifications."""

    def __init__(self) -> None:
        self._connections: dict[UUID, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: UUID, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.setdefault(user_id, []).append(ws)

    async def disconnect(self, user_id: UUID, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(user_id, [])
            if ws in conns:
                conns.remove(ws)
            if not conns:
                self._connections.pop(user_id, None)

    async def send_to_user(self, user_id: UUID, data: dict[str, Any]) -> None:
        async with self._lock:
            conns = list(self._connections.get(user_id, []))
        for ws in conns:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                await self.disconnect(user_id, ws)

    async def broadcast(self, data: dict[str, Any]) -> None:
        async with self._lock:
            all_conns = [(uid, list(conns)) for uid, conns in self._connections.items()]
        for uid, conns in all_conns:
            for ws in conns:
                try:
                    await ws.send_text(json.dumps(data))
                except Exception:
                    await self.disconnect(uid, ws)


manager = ConnectionManager()

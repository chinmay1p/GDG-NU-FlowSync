import asyncio
import json
import logging
from typing import Dict, Set

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

                                                           
    async def register(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(user_id, set()).add(websocket)
            logger.info('Registered notification websocket for user %s (total=%d)', user_id, len(self._connections[user_id]))

                                                         
    async def unregister(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            bucket = self._connections.get(user_id)
            if not bucket:
                return
            bucket.discard(websocket)
            if not bucket:
                self._connections.pop(user_id, None)
            logger.info('Unregistered notification websocket for user %s', user_id)

                                                                 
    async def emit_to_user(self, user_id: str, event: str, payload: dict) -> None:
        async with self._lock:
            targets = list(self._connections.get(user_id, set()))
        if not targets:
            logger.info('No websocket listeners for user %s; dropping event %s', user_id, event)
            return

        message = json.dumps({'event': event, 'payload': payload})
        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception as exc:
                logger.warning('Failed to deliver websocket event %s to user %s: %s', event, user_id, exc)
                stale.append(ws)
        if stale:
            async with self._lock:
                bucket = self._connections.get(user_id)
                if bucket:
                    for ws in stale:
                        bucket.discard(ws)
                    if not bucket:
                        self._connections.pop(user_id, None)


websocket_manager = WebSocketManager()

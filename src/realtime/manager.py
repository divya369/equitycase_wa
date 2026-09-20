"""In-process registry of the operator's open sockets (phone, desktop, ...).

In-process memory: this is why the app runs EXACTLY ONE uvicorn worker.
There is no replay buffer — a client that reconnects re-fetches REST state.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

from core.security import SEEDED_OPERATOR_ID

logger = structlog.get_logger("ws_manager")

# a socket that can't take a frame this fast is treated as dead
SEND_TIMEOUT_SECONDS = 5.0


class TextSocket(Protocol):
    async def send_text(self, data: str) -> None: ...


@dataclass(frozen=True)
class WsEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def frame(self) -> str:
        return json.dumps(
            {"type": self.type, "data": self.data, "ts": int(time.time())}
        )


class Connection:
    """One socket, and the operator it belongs to (push targets the others).
    Frames are sent one at a time (broadcasts and pongs come from different
    tasks)."""

    def __init__(self, socket: TextSocket, operator_id: int):
        self.socket = socket
        self.operator_id = operator_id
        self._lock = asyncio.Lock()

    async def send(self, frame: str) -> None:
        async with self._lock:
            await asyncio.wait_for(
                self.socket.send_text(frame), timeout=SEND_TIMEOUT_SECONDS
            )


class WsManager:
    def __init__(self):
        self.connections: set[Connection] = set()

    @property
    def has_clients(self) -> bool:
        return bool(self.connections)

    def connected_operator_ids(self) -> set[int]:
        """Operators watching live right now — they get no push."""
        return {c.operator_id for c in self.connections}

    def add(
        self, socket: TextSocket, operator_id: int = SEEDED_OPERATOR_ID
    ) -> Connection:
        connection = Connection(socket, operator_id)
        self.connections.add(connection)
        logger.info(
            "ws_connected", clients=len(self.connections), operator_id=operator_id
        )
        return connection

    def remove(self, connection: Connection) -> None:
        if connection in self.connections:
            self.connections.discard(connection)
            logger.info("ws_disconnected", clients=len(self.connections))

    async def publish(self, *events: WsEvent) -> None:
        """Send to every socket. A socket that errors is dropped; it never
        stops the frame reaching the others."""
        for event in events:
            await self._broadcast(event)

    async def _broadcast(self, event: WsEvent) -> None:
        connections = list(self.connections)
        if not connections:
            return
        frame = event.frame()
        results = await asyncio.gather(
            *(c.send(frame) for c in connections), return_exceptions=True
        )
        for connection, result in zip(connections, results, strict=True):
            if isinstance(result, BaseException):
                logger.info(
                    "ws_send_failed_dropping",
                    ws_event=event.type,
                    error=type(result).__name__,
                )
                self.remove(connection)


ws_manager = WsManager()

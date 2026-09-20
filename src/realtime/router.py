"""/ws?token=<jwt> — server -> client events, client -> server ping.

Frames: {"type","data","ts"} (exempt from the REST envelope). The ?token=
query is redacted from logs by config/logging.py.
"""

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, status

from core.security import InvalidTokenError, decode_access_token
from realtime.events import PONG
from realtime.manager import ws_manager

logger = structlog.get_logger("ws")

router = APIRouter()

# the client pings every 30s; two missed pings = gone
IDLE_TIMEOUT_SECONDS = 60.0


def _is_ping(text: str | None) -> bool:
    try:
        frame = json.loads(text or "")
    except ValueError:
        return False
    return isinstance(frame, dict) and frame.get("type") == "ping"


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None) -> None:
    # validate BEFORE accept(): a bad token never gets a connection
    try:
        payload = decode_access_token(token or "")
    except InvalidTokenError:
        logger.info("ws_rejected_invalid_token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    # who is watching: their devices get no push while this socket lives
    connection = ws_manager.add(websocket, payload["operator_id"])
    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive(), timeout=IDLE_TIMEOUT_SECONDS
                )
            except TimeoutError:
                logger.info("ws_idle_timeout")
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                return
            if message["type"] == "websocket.disconnect":
                return
            # any frame counts as activity; only a ping gets an answer
            if _is_ping(message.get("text")):
                await connection.send(PONG.frame())
    except Exception as e:
        logger.info("ws_connection_error", error=type(e).__name__)
    finally:
        ws_manager.remove(connection)

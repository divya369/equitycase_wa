"""P7: /ws?token= and the events every change broadcasts."""

import uuid
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from config.app_config import app_config
from core.security import create_access_token
from core.time import utcnow
from integrations.meta.errors import MetaApiError
from main import app
from modules.messages.models import MessageStatus
from realtime import router as ws_router
from realtime.events import chat_deleted
from realtime.manager import ws_manager
from tests.factories import (
    CHAT_KEYS,
    MESSAGE_KEYS,
    WA_ID,
    make_contact,
    make_messages,
    make_open_chat,
    make_outbound,
)
from tests.test_inbound import deliver, inbound
from tests.test_webhook import post_statuses, status_item

STATUS_KEYS = {"id", "wamid", "status", "client_msg_id", "chat_id", "error"}


# ---------------------------------------------------------------------------
# /ws handshake, ping, idle close
# ---------------------------------------------------------------------------
def ws_url(token: str | None) -> str:
    return "/ws" if token is None else f"/ws?token={token}"


def expired_token() -> str:
    past = utcnow() - timedelta(hours=2)
    return jwt.encode(
        {"sub": "operator", "iat": past, "exp": past + timedelta(hours=1)},
        app_config.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


@pytest.mark.parametrize(
    "token",
    [None, "", "not-a-jwt", "EXPIRED"],
    ids=["missing", "empty", "garbage", "expired"],
)
def test_bad_token_is_closed_1008(token):
    if token == "EXPIRED":
        token = expired_token()
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect(ws_url(token)):
            pass
    assert exc.value.code == 1008
    assert not ws_manager.has_clients


def test_ping_gets_pong():
    with TestClient(app).websocket_connect(ws_url(create_access_token())) as socket:
        assert ws_manager.has_clients
        socket.send_json({"type": "ping", "data": {}})
        frame = socket.receive_json()
    assert set(frame) == {"type", "data", "ts"}
    assert frame["type"] == "pong"
    assert frame["data"] == {}
    assert isinstance(frame["ts"], int)
    # disconnect unregisters the socket
    assert not ws_manager.has_clients


def test_non_ping_frames_are_ignored():
    with TestClient(app).websocket_connect(ws_url(create_access_token())) as socket:
        socket.send_text("not json")
        socket.send_json({"type": "hello"})
        socket.send_json({"type": "ping"})
        assert socket.receive_json()["type"] == "pong"


def test_idle_socket_is_closed(monkeypatch):
    monkeypatch.setattr(ws_router, "IDLE_TIMEOUT_SECONDS", 0.2)
    with TestClient(app).websocket_connect(ws_url(create_access_token())) as socket:
        with pytest.raises(WebSocketDisconnect) as exc:
            socket.receive_json()
    assert exc.value.code == 1000
    assert not ws_manager.has_clients


# ---------------------------------------------------------------------------
# broadcast rules
# ---------------------------------------------------------------------------
class DeadSocket:
    async def send_text(self, data: str) -> None:
        raise RuntimeError("connection lost")


async def test_dead_socket_is_dropped_others_still_receive(ws):
    ws_manager.add(DeadSocket())
    assert len(ws_manager.connections) == 2

    await ws_manager.publish(chat_deleted(uuid.uuid4()))
    assert ws.types == ["chat.deleted"]
    assert len(ws_manager.connections) == 1

    await ws_manager.publish(chat_deleted(uuid.uuid4()))
    assert ws.types == ["chat.deleted", "chat.deleted"]


async def test_every_client_receives(ws):
    from tests.conftest import RecordingSocket

    second = RecordingSocket()
    ws_manager.add(second)
    await ws_manager.publish(chat_deleted(uuid.uuid4()))
    assert ws.types == second.types == ["chat.deleted"]


async def test_publish_without_clients_is_a_noop():
    await ws_manager.publish(chat_deleted(uuid.uuid4()))


# ---------------------------------------------------------------------------
# webhook -> message.new / chat.updated / message.status
# ---------------------------------------------------------------------------
async def test_inbound_message_broadcasts_new_and_chat(
    client, auth_headers, business, ws
):
    await deliver(client, business, inbound("wamid.IN1"))

    assert ws.types == ["message.new", "chat.updated"]
    [message] = ws.of_type("message.new")
    [chat] = ws.of_type("chat.updated")
    assert set(message) == MESSAGE_KEYS
    assert set(chat) == CHAT_KEYS
    assert message["status"] == "delivered"
    assert chat["unread_count"] == 1
    assert chat["last_message"] == message

    # identical JSON to what REST returns
    [rest] = (
        await client.get(f"/v1/chats/{chat['id']}/messages", headers=auth_headers)
    ).json()["data"]
    assert rest == message


async def test_duplicate_inbound_broadcasts_nothing(client, business, ws):
    await deliver(client, business, inbound("wamid.IN1"))
    ws.frames.clear()
    await deliver(client, business, inbound("wamid.IN1"))
    assert ws.frames == []


async def test_status_webhook_broadcasts_status(client, business, ws):
    chat = await make_open_chat()
    msg = await make_outbound(
        chat, wamid="wamid.A", client_msg_id="c1", status=MessageStatus.SENT
    )

    await post_statuses(client, business, status_item("wamid.A", "delivered"))
    [event] = ws.of_type("message.status")
    assert set(event) == STATUS_KEYS
    assert event == {
        "id": str(msg.id),
        "wamid": "wamid.A",
        "status": "delivered",
        "client_msg_id": "c1",
        "chat_id": str(chat.id),
        "error": None,
    }


async def test_stale_status_broadcasts_nothing(client, business, ws):
    chat = await make_open_chat()
    await make_outbound(chat, wamid="wamid.A", status=MessageStatus.READ)
    await post_statuses(client, business, status_item("wamid.A", "delivered"))
    assert ws.frames == []


async def test_failed_status_carries_error(client, business, ws):
    chat = await make_open_chat()
    await make_outbound(chat, wamid="wamid.A", status=MessageStatus.SENT)
    await post_statuses(
        client,
        business,
        status_item(
            "wamid.A", "failed", errors=[{"code": 131026, "title": "Undeliverable"}]
        ),
    )
    [event] = ws.of_type("message.status")
    assert event["status"] == "failed"
    assert event["error"] == {"code": 131026, "title": "Undeliverable"}


# ---------------------------------------------------------------------------
# send / retry / delete
# ---------------------------------------------------------------------------
def send_url(chat) -> str:
    return f"/v1/chats/{chat.id}/messages"


async def test_send_broadcasts_chat_then_sent(client, auth_headers, ws):
    chat = await make_open_chat()
    resp = await client.post(
        send_url(chat),
        headers=auth_headers,
        json={"client_msg_id": "c1", "type": "text", "body": "hello"},
    )
    message_id = resp.json()["data"]["id"]

    assert ws.types == ["chat.updated", "message.status"]
    [updated] = ws.of_type("chat.updated")
    assert updated["last_message"]["id"] == message_id
    assert updated["last_message"]["status"] == "pending"
    [status] = ws.of_type("message.status")
    assert status["id"] == message_id
    assert status["status"] == "sent"
    assert status["wamid"] == "wamid.fake.1"
    assert status["client_msg_id"] == "c1"


async def test_idempotent_resend_broadcasts_nothing(client, auth_headers, ws):
    chat = await make_open_chat()
    payload = {"client_msg_id": "c1", "type": "text", "body": "hello"}
    await client.post(send_url(chat), headers=auth_headers, json=payload)
    ws.frames.clear()
    await client.post(send_url(chat), headers=auth_headers, json=payload)
    assert ws.frames == []


async def test_failed_send_broadcasts_failed(client, auth_headers, meta, ws):
    chat = await make_open_chat()
    meta.error = MetaApiError(code=131047, title="Re-engagement message")
    await client.post(
        send_url(chat),
        headers=auth_headers,
        json={"client_msg_id": "c1", "type": "text", "body": "hello"},
    )
    [status] = ws.of_type("message.status")
    assert status["status"] == "failed"
    assert status["wamid"] is None
    assert status["error"] == {"code": 131047, "title": "Re-engagement message"}


async def test_retry_broadcasts_pending_then_sent(client, auth_headers, ws):
    chat = await make_open_chat()
    failed = await make_outbound(
        chat, status=MessageStatus.FAILED, error_code=1, error_title="x"
    )
    await client.post(f"/v1/messages/{failed.id}/retry", headers=auth_headers)
    assert [s["status"] for s in ws.of_type("message.status")] == ["pending", "sent"]


async def test_delete_last_message_broadcasts_deleted_and_chat(
    client, auth_headers, ws
):
    chat = await make_open_chat()
    older, newest = await make_messages(chat, 2)

    await client.delete(
        f"/v1/chats/{chat.id}/messages/{newest.id}", headers=auth_headers
    )
    assert ws.types == ["message.deleted", "chat.updated"]
    assert ws.of_type("message.deleted") == [
        {"chat_id": str(chat.id), "message_id": str(newest.id)}
    ]
    [updated] = ws.of_type("chat.updated")
    assert updated["last_message"]["id"] == str(older.id)


async def test_delete_older_message_broadcasts_only_deleted(client, auth_headers, ws):
    chat = await make_open_chat()
    older, _ = await make_messages(chat, 2)
    await client.delete(
        f"/v1/chats/{chat.id}/messages/{older.id}", headers=auth_headers
    )
    assert ws.types == ["message.deleted"]


# ---------------------------------------------------------------------------
# chats / contacts
# ---------------------------------------------------------------------------
async def test_read_broadcasts_chat_once(client, auth_headers, ws):
    chat = await make_open_chat(unread_count=2)
    await make_messages(chat, 2)

    await client.post(f"/v1/chats/{chat.id}/read", headers=auth_headers)
    [updated] = ws.of_type("chat.updated")
    assert updated["unread_count"] == 0
    assert updated["last_message"]["status"] == "read"

    # nothing changed the second time -> no frame
    await client.post(f"/v1/chats/{chat.id}/read", headers=auth_headers)
    assert len(ws.frames) == 1


async def test_read_broadcasts_even_when_meta_fails(client, auth_headers, meta, ws):
    chat = await make_open_chat(unread_count=1)
    await make_messages(chat, 1)
    meta.error = MetaApiError(code=100, title="Invalid parameter")
    await client.post(f"/v1/chats/{chat.id}/read", headers=auth_headers)
    assert ws.types == ["chat.updated"]


async def test_clear_broadcasts_empty_chat(client, auth_headers, ws):
    chat = await make_open_chat(unread_count=1)
    await make_messages(chat, 1)
    await client.post(f"/v1/chats/{chat.id}/clear", headers=auth_headers)
    [updated] = ws.of_type("chat.updated")
    assert updated["last_message"] is None
    assert updated["unread_count"] == 0


async def test_delete_chat_broadcasts_deleted(client, auth_headers, ws):
    chat = await make_open_chat()
    await client.delete(f"/v1/chats/{chat.id}", headers=auth_headers)
    assert ws.frames[0]["type"] == "chat.deleted"
    assert ws.of_type("chat.deleted") == [{"chat_id": str(chat.id)}]


async def test_delete_contact_broadcasts_its_chat_deleted(client, auth_headers, ws):
    chat = await make_open_chat()
    await client.delete(f"/v1/contacts/{WA_ID}", headers=auth_headers)
    assert ws.of_type("chat.deleted") == [{"chat_id": str(chat.id)}]


async def test_delete_contact_without_chat_broadcasts_nothing(client, auth_headers, ws):
    await make_contact()
    await client.delete(f"/v1/contacts/{WA_ID}", headers=auth_headers)
    assert ws.frames == []


async def test_failed_request_broadcasts_nothing(client, auth_headers, ws):
    await client.delete(f"/v1/chats/{uuid.uuid4()}", headers=auth_headers)
    assert ws.frames == []

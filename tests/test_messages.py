import uuid
from datetime import timedelta

import pytest

from core.database import SessionFactory
from core.time import utcnow
from integrations.meta.errors import MetaApiError
from modules.messages.models import MessageStatus
from modules.messages.repository import MessageRepository
from tests.factories import (
    MESSAGE_KEYS,
    WA_ID,
    assert_error,
    count,
    get_message,
    make_chat,
    make_messages,
    make_open_chat,
    make_outbound,
)


def send_url(chat) -> str:
    return f"/v1/chats/{chat.id}/messages"


def body(client_msg_id: str = "client-1", text: str = "Hello there") -> dict:
    return {"client_msg_id": client_msg_id, "type": "text", "body": text}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"/v1/chats/{uuid.uuid4()}/messages"),
        ("POST", f"/v1/messages/{uuid.uuid4()}/retry"),
        ("DELETE", f"/v1/chats/{uuid.uuid4()}/messages/{uuid.uuid4()}"),
    ],
)
async def test_routes_require_jwt(client, method, path):
    resp = await client.request(method, path)
    assert_error(resp, 401, "unauthorized")


# ---------------------------------------------------------------------------
# POST /v1/chats/{id}/messages
# ---------------------------------------------------------------------------
async def test_send_returns_pending_then_delivers(client, auth_headers, meta, business):
    chat = await make_open_chat()

    resp = await client.post(send_url(chat), headers=auth_headers, json=body())
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert set(data) == MESSAGE_KEYS
    # the response is the row as stored — before Meta was called
    assert data["status"] == "pending"
    assert data["client_msg_id"] == "client-1"
    assert data["from"] == business.wa_id
    assert data["text"] == {"body": "Hello there"}
    assert data["error"] is None

    # the background task ran after the response
    assert meta.sent == [
        {
            "phone_number_id": business.phone_number_id,
            "to": WA_ID,
            "body": "Hello there",
            "reply_to_wamid": None,
        }
    ]
    stored = await get_message(uuid.UUID(data["id"]))
    assert stored.status == MessageStatus.SENT
    assert stored.wamid == "wamid.fake.1"


async def test_send_updates_chat_last_message_and_order(client, auth_headers):
    now = utcnow()
    older = await make_open_chat("911111111111", updated_at=now - timedelta(days=3))
    await make_open_chat("912222222222", updated_at=now - timedelta(days=1))

    resp = await client.post(send_url(older), headers=auth_headers, json=body())
    message_id = resp.json()["data"]["id"]

    chats = (await client.get("/v1/chats", headers=auth_headers)).json()["data"]
    assert chats[0]["id"] == str(older.id)
    assert chats[0]["last_message"]["id"] == message_id
    assert chats[0]["last_message"]["status"] == "sent"


async def test_send_is_idempotent_on_client_msg_id(client, auth_headers, meta):
    chat = await make_open_chat()

    first = await client.post(send_url(chat), headers=auth_headers, json=body())
    again = await client.post(send_url(chat), headers=auth_headers, json=body())
    assert again.status_code == 201
    assert again.json()["data"]["id"] == first.json()["data"]["id"]
    assert await count("messages") == 1
    # Meta called once only
    assert len(meta.sent) == 1


async def test_same_client_msg_id_in_other_chat_is_new(client, auth_headers):
    a = await make_open_chat("911111111111")
    b = await make_open_chat("912222222222")
    await client.post(send_url(a), headers=auth_headers, json=body())
    await client.post(send_url(b), headers=auth_headers, json=body())
    assert await count("messages") == 2


async def test_send_with_reply_context(client, auth_headers, meta):
    chat = await make_open_chat()
    payload = {**body(), "context": {"id": "wamid.parent"}}
    resp = await client.post(send_url(chat), headers=auth_headers, json=payload)
    assert resp.json()["data"]["context"] == {"id": "wamid.parent"}
    assert meta.sent[0]["reply_to_wamid"] == "wamid.parent"


@pytest.mark.parametrize(
    "last_inbound_at",
    [None, "expired"],
    ids=["customer-never-wrote", "older-than-24h"],
)
async def test_send_outside_window_is_409(client, auth_headers, meta, last_inbound_at):
    if last_inbound_at == "expired":
        last_inbound_at = utcnow() - timedelta(hours=24, minutes=1)
    chat = await make_chat(last_inbound_at=last_inbound_at)

    resp = await client.post(send_url(chat), headers=auth_headers, json=body())
    assert_error(resp, 409, "conversation_window_closed")
    assert await count("messages") == 0
    assert meta.sent == []


async def test_idempotent_repeat_wins_over_closed_window(client, auth_headers):
    """A client retry after a timeout must get its row back, even if the
    window closed in between."""
    chat = await make_chat()
    existing = await make_outbound(chat, client_msg_id="client-1")
    resp = await client.post(send_url(chat), headers=auth_headers, json=body())
    assert resp.status_code == 201
    assert resp.json()["data"]["id"] == str(existing.id)


async def test_meta_error_marks_failed(client, auth_headers, meta):
    chat = await make_open_chat()
    meta.error = MetaApiError(
        code=131047, title="Re-engagement message", http_status=400
    )

    resp = await client.post(send_url(chat), headers=auth_headers, json=body())
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "pending"

    [m] = (await client.get(send_url(chat), headers=auth_headers)).json()["data"]
    assert m["status"] == "failed"
    assert m["error"] == {"code": 131047, "title": "Re-engagement message"}


async def test_unexpected_error_marks_failed(client, auth_headers, meta):
    chat = await make_open_chat()
    meta.error = RuntimeError("boom")

    await client.post(send_url(chat), headers=auth_headers, json=body())
    [m] = (await client.get(send_url(chat), headers=auth_headers)).json()["data"]
    assert m["status"] == "failed"
    assert m["error"] == {"code": None, "title": "Could not send the message"}


async def test_send_unknown_chat_is_404(client, auth_headers):
    resp = await client.post(
        f"/v1/chats/{uuid.uuid4()}/messages", headers=auth_headers, json=body()
    )
    assert_error(resp, 404, "not_found")


@pytest.mark.parametrize(
    "payload",
    [
        {"client_msg_id": "c", "type": "text", "body": ""},
        {"client_msg_id": "c", "type": "text", "body": "   "},
        {"client_msg_id": "c", "type": "text", "body": "x" * 4097},
        {"client_msg_id": "c", "type": "image", "body": "hi"},
        {"client_msg_id": "", "type": "text", "body": "hi"},
        {"type": "text", "body": "hi"},
    ],
    ids=["empty", "blank", "too-long", "image", "empty-id", "no-id"],
)
async def test_send_validates(client, auth_headers, payload):
    chat = await make_open_chat()
    resp = await client.post(send_url(chat), headers=auth_headers, json=payload)
    assert_error(resp, 422, "validation_error")


# ---------------------------------------------------------------------------
# monotonic status
# ---------------------------------------------------------------------------
async def test_status_never_moves_backwards():
    chat = await make_open_chat()
    message = await make_outbound(chat, status=MessageStatus.READ, wamid="w1")

    async with SessionFactory() as session:
        repo = MessageRepository(session)
        assert await repo.mark_sent(message.id, "w2") is False
        assert await repo.reset_for_retry(message.id) is False
        await session.commit()

    stored = await get_message(message.id)
    assert stored.status == MessageStatus.READ
    assert stored.wamid == "w1"


# ---------------------------------------------------------------------------
# POST /v1/messages/{id}/retry
# ---------------------------------------------------------------------------
async def test_retry_failed_message(client, auth_headers, meta):
    chat = await make_open_chat()
    failed = await make_outbound(
        chat,
        client_msg_id="client-1",
        status=MessageStatus.FAILED,
        error_code=131026,
        error_title="Undeliverable",
    )

    resp = await client.post(f"/v1/messages/{failed.id}/retry", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["id"] == str(failed.id)
    assert data["status"] == "pending"
    assert data["error"] is None

    stored = await get_message(failed.id)
    assert stored.status == MessageStatus.SENT
    assert stored.error_code is None and stored.error_title is None
    assert len(meta.sent) == 1


@pytest.mark.parametrize("status", [MessageStatus.PENDING, MessageStatus.READ])
async def test_retry_non_failed_is_409(client, auth_headers, status):
    chat = await make_open_chat()
    message = await make_outbound(chat, status=status)
    resp = await client.post(f"/v1/messages/{message.id}/retry", headers=auth_headers)
    assert_error(resp, 409, "conflict")


async def test_retry_inbound_is_409(client, auth_headers):
    chat = await make_open_chat()
    [inbound] = await make_messages(chat, 1)
    resp = await client.post(f"/v1/messages/{inbound.id}/retry", headers=auth_headers)
    assert_error(resp, 409, "conflict")


async def test_retry_outside_window_is_409(client, auth_headers, meta):
    chat = await make_chat()
    failed = await make_outbound(chat, status=MessageStatus.FAILED)
    resp = await client.post(f"/v1/messages/{failed.id}/retry", headers=auth_headers)
    assert_error(resp, 409, "conversation_window_closed")
    assert (await get_message(failed.id)).status == MessageStatus.FAILED
    assert meta.sent == []


async def test_retry_unknown_is_404(client, auth_headers):
    resp = await client.post(f"/v1/messages/{uuid.uuid4()}/retry", headers=auth_headers)
    assert_error(resp, 404, "not_found")


# ---------------------------------------------------------------------------
# DELETE /v1/chats/{id}/messages/{messageId}
# ---------------------------------------------------------------------------
async def test_delete_last_message_moves_last_message_back(client, auth_headers):
    chat = await make_open_chat()
    msgs = await make_messages(chat, 3)

    resp = await client.delete(
        f"/v1/chats/{chat.id}/messages/{msgs[-1].id}", headers=auth_headers
    )
    assert resp.status_code == 204 and resp.content == b""
    assert await count("messages") == 2

    [item] = (await client.get("/v1/chats", headers=auth_headers)).json()["data"]
    assert item["last_message"]["id"] == str(msgs[1].id)


async def test_delete_only_message_nulls_last_message(client, auth_headers):
    chat = await make_open_chat()
    [only] = await make_messages(chat, 1)
    await client.delete(f"/v1/chats/{chat.id}/messages/{only.id}", headers=auth_headers)
    [item] = (await client.get("/v1/chats", headers=auth_headers)).json()["data"]
    assert item["last_message"] is None


async def test_delete_message_of_other_chat_is_404(client, auth_headers):
    a = await make_open_chat("911111111111")
    b = await make_open_chat("912222222222")
    [m] = await make_messages(a, 1)
    resp = await client.delete(
        f"/v1/chats/{b.id}/messages/{m.id}", headers=auth_headers
    )
    assert_error(resp, 404, "not_found")
    assert await count("messages") == 1

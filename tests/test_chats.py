import uuid
from datetime import timedelta

import pytest

from core.database import SessionFactory
from core.time import to_unix_str, utcnow
from modules.messages.models import Message, MessageDirection, MessageStatus
from tests.factories import (
    BUSINESS_WA_ID,
    CHAT_KEYS,
    MESSAGE_KEYS,
    USER_KEYS,
    WA_ID,
    assert_error,
    count,
    make_chat,
    make_contact,
    make_messages,
)


# ---------------------------------------------------------------------------
# JWT is enforced on every new route
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/chats"),
        ("POST", "/v1/chats"),
        ("DELETE", f"/v1/chats/{uuid.uuid4()}"),
        ("POST", f"/v1/chats/{uuid.uuid4()}/clear"),
        ("GET", f"/v1/chats/{uuid.uuid4()}/messages"),
        ("GET", "/v1/contacts"),
        ("POST", "/v1/contacts"),
        ("DELETE", f"/v1/contacts/{WA_ID}"),
    ],
)
async def test_routes_require_jwt(client, method, path):
    resp = await client.request(method, path)
    assert_error(resp, 401, "unauthorized")


# ---------------------------------------------------------------------------
# GET /v1/chats
# ---------------------------------------------------------------------------
async def test_list_chats_empty(client, auth_headers):
    resp = await client.get("/v1/chats", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"] == []
    assert resp.json()["meta"]["request_id"]


async def test_list_chats_shape(client, auth_headers):
    chat = await make_chat(unread_count=2)
    messages = await make_messages(chat, 3)

    resp = await client.get("/v1/chats", headers=auth_headers)
    assert resp.status_code == 200
    [item] = resp.json()["data"]

    assert set(item) == CHAT_KEYS
    assert item["id"] == str(chat.id)
    assert item["unread_count"] == 2
    assert item["is_pinned"] is False and item["is_muted"] is False

    assert set(item["contact"]) == USER_KEYS
    assert item["contact"]["wa_id"] == WA_ID
    assert item["contact"]["is_online"] is False
    assert item["contact"]["last_seen"] is None

    last = item["last_message"]
    assert set(last) == MESSAGE_KEYS
    assert last["id"] == str(messages[-1].id)
    assert last["from"] == WA_ID
    assert last["text"] == {"body": "msg 2"}
    assert last["status"] == "delivered"
    assert last["timestamp"] == to_unix_str(messages[-1].created_at)
    assert isinstance(last["timestamp"], str)
    assert last["context"] is None
    assert last["error"] is None


async def test_list_chats_order_pinned_then_recent(client, auth_headers):
    now = utcnow()
    old = await make_chat("911111111111", updated_at=now - timedelta(days=2))
    new = await make_chat("912222222222", updated_at=now)
    pinned = await make_chat(
        "913333333333", is_pinned=True, updated_at=now - timedelta(days=9)
    )

    resp = await client.get("/v1/chats", headers=auth_headers)
    ids = [c["id"] for c in resp.json()["data"]]
    assert ids == [str(pinned.id), str(new.id), str(old.id)]


async def test_chat_without_messages_has_null_last_message(client, auth_headers):
    await make_chat()
    resp = await client.get("/v1/chats", headers=auth_headers)
    [item] = resp.json()["data"]
    # the key is present, not dropped
    assert "last_message" in item and item["last_message"] is None


# ---------------------------------------------------------------------------
# POST /v1/chats (find-or-create)
# ---------------------------------------------------------------------------
async def test_open_chat_creates_then_finds(client, auth_headers):
    await make_contact()

    first = await client.post("/v1/chats", headers=auth_headers, json={"wa_id": WA_ID})
    assert first.status_code == 200, first.text
    assert set(first.json()["data"]) == CHAT_KEYS
    assert first.json()["data"]["last_message"] is None

    # '+' and spacing tolerated; same chat returned
    again = await client.post(
        "/v1/chats", headers=auth_headers, json={"wa_id": "+91 98200 11223"}
    )
    assert again.json()["data"]["id"] == first.json()["data"]["id"]
    assert await count("chats") == 1


async def test_open_chat_unknown_contact_is_404(client, auth_headers):
    resp = await client.post("/v1/chats", headers=auth_headers, json={"wa_id": WA_ID})
    assert_error(resp, 404, "not_found")
    assert await count("chats") == 0


async def test_open_chat_validates(client, auth_headers):
    resp = await client.post("/v1/chats", headers=auth_headers, json={"wa_id": "x"})
    assert_error(resp, 422, "validation_error")


# ---------------------------------------------------------------------------
# DELETE /v1/chats/{id} and POST /clear
# ---------------------------------------------------------------------------
async def test_delete_chat_cascades_messages_keeps_contact(client, auth_headers):
    chat = await make_chat()
    await make_messages(chat, 3)

    resp = await client.delete(f"/v1/chats/{chat.id}", headers=auth_headers)
    assert resp.status_code == 204 and resp.content == b""
    assert await count("chats") == 0
    assert await count("messages") == 0
    assert await count("contacts") == 1


async def test_delete_missing_chat_is_404(client, auth_headers):
    resp = await client.delete(f"/v1/chats/{uuid.uuid4()}", headers=auth_headers)
    assert_error(resp, 404, "not_found")


async def test_bad_chat_id_is_422(client, auth_headers):
    resp = await client.delete("/v1/chats/not-a-uuid", headers=auth_headers)
    assert_error(resp, 422, "validation_error")


async def test_clear_chat_empties_but_keeps_row(client, auth_headers):
    chat = await make_chat(unread_count=4)
    await make_messages(chat, 3)

    resp = await client.post(f"/v1/chats/{chat.id}/clear", headers=auth_headers)
    assert resp.status_code == 204 and resp.content == b""
    assert await count("messages") == 0

    [item] = (await client.get("/v1/chats", headers=auth_headers)).json()["data"]
    assert item["id"] == str(chat.id)
    assert item["last_message"] is None
    assert item["unread_count"] == 0


async def test_clear_missing_chat_is_404(client, auth_headers):
    resp = await client.post(f"/v1/chats/{uuid.uuid4()}/clear", headers=auth_headers)
    assert_error(resp, 404, "not_found")


# ---------------------------------------------------------------------------
# GET /v1/chats/{id}/messages
# ---------------------------------------------------------------------------
async def test_messages_ascending_and_paginated(client, auth_headers):
    chat = await make_chat()
    msgs = await make_messages(chat, 5)
    url = f"/v1/chats/{chat.id}/messages"

    page1 = (await client.get(url, headers=auth_headers, params={"limit": 2})).json()
    assert [m["text"]["body"] for m in page1["data"]] == ["msg 3", "msg 4"]
    assert set(page1["data"][0]) == MESSAGE_KEYS

    before = msgs[3].created_at.isoformat()
    page2 = (
        await client.get(
            url, headers=auth_headers, params={"limit": 2, "before": before}
        )
    ).json()
    assert [m["text"]["body"] for m in page2["data"]] == ["msg 1", "msg 2"]

    before = msgs[1].created_at.isoformat()
    page3 = (
        await client.get(
            url, headers=auth_headers, params={"limit": 2, "before": before}
        )
    ).json()
    assert [m["text"]["body"] for m in page3["data"]] == ["msg 0"]


async def test_messages_default_limit_is_50(client, auth_headers):
    chat = await make_chat()
    await make_messages(chat, 55)
    resp = await client.get(f"/v1/chats/{chat.id}/messages", headers=auth_headers)
    data = resp.json()["data"]
    assert len(data) == 50
    assert data[-1]["text"]["body"] == "msg 54"


async def test_failed_outbound_message_shape(client, auth_headers):
    chat = await make_chat()
    async with SessionFactory() as session:
        session.add(
            Message(
                chat_id=chat.id,
                sender_wa_id=BUSINESS_WA_ID,
                direction=MessageDirection.OUT,
                body="hello",
                client_msg_id="client-1",
                reply_to_wamid="wamid.parent",
                status=MessageStatus.FAILED,
                error_code=131047,
                error_title="Re-engagement message",
            )
        )
        await session.commit()

    resp = await client.get(f"/v1/chats/{chat.id}/messages", headers=auth_headers)
    [m] = resp.json()["data"]
    assert m["from"] == BUSINESS_WA_ID
    assert m["status"] == "failed"
    assert m["client_msg_id"] == "client-1"
    assert m["context"] == {"id": "wamid.parent"}
    assert m["error"] == {"code": 131047, "title": "Re-engagement message"}


async def test_messages_unknown_chat_is_404(client, auth_headers):
    resp = await client.get(f"/v1/chats/{uuid.uuid4()}/messages", headers=auth_headers)
    assert_error(resp, 404, "not_found")


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"before": "yesterday"}]
)
async def test_messages_validates_query(client, auth_headers, params):
    chat = await make_chat()
    resp = await client.get(
        f"/v1/chats/{chat.id}/messages", headers=auth_headers, params=params
    )
    assert_error(resp, 422, "validation_error")


# ---------------------------------------------------------------------------
# contacts
# ---------------------------------------------------------------------------
async def test_create_and_list_contacts(client, auth_headers):
    resp = await client.post(
        "/v1/contacts",
        headers=auth_headers,
        json={"name": "  Ananya Mehta ", "phone": "91 98200 11223"},
    )
    assert resp.status_code == 201, resp.text
    user = resp.json()["data"]
    assert set(user) == USER_KEYS
    assert user["wa_id"] == WA_ID
    assert user["phone"] == "+91 98200 11223"
    assert user["name"] == "Ananya Mehta"
    assert user["is_online"] is False and user["last_seen"] is None

    await client.post(
        "/v1/contacts",
        headers=auth_headers,
        json={"name": "Aarav", "phone": "+919000000001"},
    )
    listed = (await client.get("/v1/contacts", headers=auth_headers)).json()["data"]
    assert [c["name"] for c in listed] == ["Aarav", "Ananya Mehta"]


async def test_create_duplicate_contact_is_409(client, auth_headers):
    body = {"name": "Ananya", "phone": "+919820011223"}
    await client.post("/v1/contacts", headers=auth_headers, json=body)
    resp = await client.post(
        "/v1/contacts",
        headers=auth_headers,
        json={"name": "Other", "phone": "+91 98200 11223"},
    )
    assert_error(resp, 409, "conflict")


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "phone": "+919820011223"},
        {"name": "A", "phone": "abc"},
        {"name": "A"},
    ],
)
async def test_create_contact_validates(client, auth_headers, body):
    resp = await client.post("/v1/contacts", headers=auth_headers, json=body)
    assert_error(resp, 422, "validation_error")


async def test_delete_contact_cascades_chat(client, auth_headers):
    chat = await make_chat()
    await make_messages(chat, 2)

    resp = await client.delete(f"/v1/contacts/{WA_ID}", headers=auth_headers)
    assert resp.status_code == 204 and resp.content == b""
    assert await count("contacts") == 0
    assert await count("chats") == 0
    assert await count("messages") == 0


async def test_delete_missing_contact_is_404(client, auth_headers):
    resp = await client.delete(f"/v1/contacts/{WA_ID}", headers=auth_headers)
    assert_error(resp, 404, "not_found")

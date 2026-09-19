"""P6: inbound webhook messages -> contact / chat / message, and chat read."""

import json
import uuid
from datetime import timedelta

import pytest

from core.database import SessionFactory
from core.time import to_unix_str, utcnow
from integrations.meta.errors import MetaApiError
from modules.chats.models import Chat
from modules.contacts.models import Contact
from modules.messages.models import MessageDirection, MessageStatus
from modules.webhook.signature import compute_signature
from tests.factories import (
    MESSAGE_KEYS,
    WA_ID,
    assert_error,
    count,
    make_contact,
    make_outbound,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def inbound(
    wamid: str = "wamid.IN1",
    *,
    sender: str = WA_ID,
    kind: str = "text",
    content: dict | None = None,
    ts=None,
    **extra,
) -> dict:
    message = {
        "from": sender,
        "id": wamid,
        "timestamp": str(ts if ts is not None else int(utcnow().timestamp())),
        "type": kind,
        **extra,
    }
    message[kind] = content if content is not None else {"body": "Hi there"}
    return message


async def deliver(client, business, *messages: dict, name: str | None = "Ananya"):
    """POST a signed webhook carrying inbound messages (+ contacts[])."""
    senders = {m["from"] for m in messages}
    value = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "15550000000",
            "phone_number_id": business.phone_number_id,
        },
        "contacts": [
            {"profile": {"name": name} if name else {}, "wa_id": s} for s in senders
        ],
        "messages": list(messages),
    }
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "W", "changes": [{"field": "messages", "value": value}]}],
        }
    ).encode()
    resp = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": compute_signature(body)},
    )
    assert resp.status_code == 200, resp.text


async def get_contact(wa_id: str = WA_ID) -> Contact | None:
    async with SessionFactory() as session:
        return await session.get(Contact, wa_id)


async def only_chat(client, auth_headers) -> dict:
    [chat] = (await client.get("/v1/chats", headers=auth_headers)).json()["data"]
    return chat


async def messages_of(client, auth_headers, chat_id) -> list[dict]:
    resp = await client.get(f"/v1/chats/{chat_id}/messages", headers=auth_headers)
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# new customer
# ---------------------------------------------------------------------------
async def test_first_message_creates_contact_chat_and_message(
    client, auth_headers, business
):
    ts = int((utcnow() - timedelta(minutes=5)).timestamp())
    await deliver(client, business, inbound(ts=ts))

    contact = await get_contact()
    assert contact.name == "Ananya"
    assert contact.phone == f"+{WA_ID}"

    chat = await only_chat(client, auth_headers)
    assert chat["contact"]["wa_id"] == WA_ID
    assert chat["contact"]["name"] == "Ananya"
    assert chat["unread_count"] == 1

    last = chat["last_message"]
    assert set(last) == MESSAGE_KEYS
    assert last["from"] == WA_ID
    assert last["type"] == "text"
    assert last["text"] == {"body": "Hi there"}
    # inbound is stored as delivered until the operator opens the chat
    assert last["status"] == "delivered"
    # Meta's timestamp, not our receive time
    assert last["timestamp"] == str(ts)
    assert last["client_msg_id"] is None
    assert last["context"] is None


async def test_message_opens_the_24h_window(client, auth_headers, business, meta):
    await deliver(client, business, inbound())
    chat = await only_chat(client, auth_headers)

    resp = await client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={"client_msg_id": "r1", "type": "text", "body": "Hello!"},
    )
    assert resp.status_code == 201, resp.text
    assert meta.sent[0]["to"] == WA_ID


async def test_old_message_does_not_open_window(client, auth_headers, business):
    """A replayed message from 2 days ago must not reopen the window."""
    old = int((utcnow() - timedelta(days=2)).timestamp())
    await deliver(client, business, inbound(ts=old))
    chat = await only_chat(client, auth_headers)
    resp = await client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=auth_headers,
        json={"client_msg_id": "r1", "type": "text", "body": "Hello!"},
    )
    assert_error(resp, 409, "conversation_window_closed")


async def test_no_profile_name_uses_phone(client, business):
    await deliver(client, business, inbound(), name=None)
    contact = await get_contact()
    assert contact.name == f"+{WA_ID}"


# ---------------------------------------------------------------------------
# existing customer
# ---------------------------------------------------------------------------
async def test_more_messages_same_chat_unread_counts(client, auth_headers, business):
    await deliver(client, business, inbound("wamid.1"))
    await deliver(client, business, inbound("wamid.2"), inbound("wamid.3"))

    assert await count("chats") == 1
    chat = await only_chat(client, auth_headers)
    assert chat["unread_count"] == 3
    assert len(await messages_of(client, auth_headers, chat["id"])) == 3


async def test_operator_chosen_name_is_kept(client, business):
    await make_contact(WA_ID, name="Ananya (Mumbai office)")
    await deliver(client, business, inbound(), name="ananya_m")
    assert (await get_contact()).name == "Ananya (Mumbai office)"


async def test_placeholder_name_is_replaced(client, business):
    await deliver(client, business, inbound("wamid.1"), name=None)
    await deliver(client, business, inbound("wamid.2"), name="Ananya")
    assert (await get_contact()).name == "Ananya"


async def test_contact_added_before_first_message(client, auth_headers, business):
    """Operator adds the contact, THEN the customer writes: same chat."""
    await client.post(
        "/v1/contacts",
        headers=auth_headers,
        json={"name": "Ananya", "phone": "+91 98200 11223"},
    )
    opened = await client.post("/v1/chats", headers=auth_headers, json={"wa_id": WA_ID})
    await deliver(client, business, inbound())
    chat = await only_chat(client, auth_headers)
    assert chat["id"] == opened.json()["data"]["id"]
    assert chat["contact"]["name"] == "Ananya"
    assert chat["contact"]["phone"] == "+91 98200 11223"


async def test_duplicate_wamid_is_stored_once(client, auth_headers, business):
    await deliver(client, business, inbound("wamid.SAME"))
    await deliver(client, business, inbound("wamid.SAME"))
    assert await count("messages") == 1
    assert (await only_chat(client, auth_headers))["unread_count"] == 1


async def test_out_of_order_keeps_newest_as_last_message(
    client, auth_headers, business
):
    now = int(utcnow().timestamp())
    await deliver(
        client, business, inbound("wamid.NEW", ts=now, content={"body": "new"})
    )
    await deliver(
        client, business, inbound("wamid.OLD", ts=now - 60, content={"body": "old"})
    )
    chat = await only_chat(client, auth_headers)
    assert chat["last_message"]["text"]["body"] == "new"
    bodies = [
        m["text"]["body"] for m in await messages_of(client, auth_headers, chat["id"])
    ]
    assert bodies == ["old", "new"]


async def test_new_message_moves_chat_to_top(client, auth_headers, business):
    await deliver(client, business, inbound("wamid.A", sender="911111111111"))
    await deliver(client, business, inbound("wamid.B", sender="912222222222"))
    await deliver(client, business, inbound("wamid.C", sender="911111111111"))
    chats = (await client.get("/v1/chats", headers=auth_headers)).json()["data"]
    assert [c["contact"]["wa_id"] for c in chats] == ["911111111111", "912222222222"]


async def test_reply_context_is_kept(client, auth_headers, business):
    await deliver(
        client, business, inbound(context={"from": "x", "id": "wamid.PARENT"})
    )
    chat = await only_chat(client, auth_headers)
    assert chat["last_message"]["context"] == {"id": "wamid.PARENT"}


# ---------------------------------------------------------------------------
# message types
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "content", "body"),
    [
        (
            "image",
            {"id": "MEDIA1", "mime_type": "image/jpeg", "caption": "look"},
            "look",
        ),
        ("image", {"id": "MEDIA1", "mime_type": "image/jpeg"}, ""),
        ("video", {"id": "MEDIA1", "mime_type": "video/mp4"}, ""),
        ("audio", {"id": "MEDIA1", "mime_type": "audio/ogg", "voice": True}, ""),
        ("sticker", {"id": "MEDIA1", "mime_type": "image/webp"}, ""),
        (
            "document",
            {"id": "MEDIA1", "mime_type": "application/pdf", "filename": "bill.pdf"},
            "bill.pdf",
        ),
    ],
)
async def test_media_messages(client, auth_headers, business, kind, content, body):
    await deliver(client, business, inbound(kind=kind, content=content))
    chat = await only_chat(client, auth_headers)
    last = chat["last_message"]
    assert last["type"] == kind
    assert last["text"] == {"body": body}
    # downloaded to R2 in P10
    assert last["media_url"] is None

    async with SessionFactory() as session:
        from sqlmodel import select

        from modules.messages.models import Message

        stored = (await session.exec(select(Message))).one()
    assert stored.media_id == "MEDIA1"
    assert stored.media_mime == content["mime_type"]
    assert stored.direction == MessageDirection.IN


async def test_location_message(client, auth_headers, business):
    await deliver(
        client,
        business,
        inbound(kind="location", content={"latitude": 19.0, "longitude": 72.8}),
    )
    last = (await only_chat(client, auth_headers))["last_message"]
    assert last["type"] == "location"
    assert last["text"] == {"body": "📍 Location"}


async def test_button_reply_becomes_text(client, auth_headers, business):
    await deliver(
        client,
        business,
        inbound(
            kind="interactive",
            content={
                "type": "button_reply",
                "button_reply": {"id": "y", "title": "Yes"},
            },
        ),
    )
    last = (await only_chat(client, auth_headers))["last_message"]
    assert last["type"] == "text"
    assert last["text"] == {"body": "Yes"}


async def test_unknown_type_is_stored_as_text(client, auth_headers, business):
    await deliver(client, business, inbound(kind="order", content={"catalog_id": "1"}))
    last = (await only_chat(client, auth_headers))["last_message"]
    assert last["type"] == "text"
    assert last["text"] == {"body": "[Unsupported message]"}


async def test_reaction_is_not_a_message(client, business):
    await deliver(
        client,
        business,
        inbound(kind="reaction", content={"message_id": "wamid.X", "emoji": "👍"}),
    )
    assert await count("messages") == 0
    assert await count("chats") == 0


# ---------------------------------------------------------------------------
# POST /v1/chats/{id}/read
# ---------------------------------------------------------------------------
async def test_read_marks_messages_and_calls_meta(client, auth_headers, business, meta):
    now = int(utcnow().timestamp())
    await deliver(client, business, inbound("wamid.1", ts=now - 10))
    await deliver(client, business, inbound("wamid.2", ts=now))
    chat = await only_chat(client, auth_headers)

    resp = await client.post(f"/v1/chats/{chat['id']}/read", headers=auth_headers)
    assert resp.status_code == 204 and resp.content == b""

    chat = await only_chat(client, auth_headers)
    assert chat["unread_count"] == 0
    statuses = {
        m["status"] for m in await messages_of(client, auth_headers, chat["id"])
    }
    assert statuses == {"read"}
    # one call, for the NEWEST inbound message (it covers the earlier ones)
    assert meta.read == ["wamid.2"]


async def test_read_again_does_not_call_meta(client, auth_headers, business, meta):
    await deliver(client, business, inbound())
    chat = await only_chat(client, auth_headers)
    await client.post(f"/v1/chats/{chat['id']}/read", headers=auth_headers)
    await client.post(f"/v1/chats/{chat['id']}/read", headers=auth_headers)
    assert len(meta.read) == 1


async def test_read_leaves_outbound_untouched(client, auth_headers, business):
    await deliver(client, business, inbound())
    chat_id = uuid.UUID((await only_chat(client, auth_headers))["id"])
    async with SessionFactory() as session:
        chat = await session.get(Chat, chat_id)
    out = await make_outbound(chat, status=MessageStatus.DELIVERED, wamid="wamid.OUT")

    await client.post(f"/v1/chats/{chat_id}/read", headers=auth_headers)
    async with SessionFactory() as session:
        from modules.messages.models import Message

        assert (await session.get(Message, out.id)).status == MessageStatus.DELIVERED


async def test_read_succeeds_when_meta_fails(client, auth_headers, business, meta):
    await deliver(client, business, inbound())
    chat = await only_chat(client, auth_headers)
    meta.error = MetaApiError(code=100, title="Invalid parameter")

    resp = await client.post(f"/v1/chats/{chat['id']}/read", headers=auth_headers)
    assert resp.status_code == 204
    assert (await only_chat(client, auth_headers))["unread_count"] == 0


async def test_read_unknown_chat_is_404(client, auth_headers):
    resp = await client.post(f"/v1/chats/{uuid.uuid4()}/read", headers=auth_headers)
    assert_error(resp, 404, "not_found")


async def test_read_requires_jwt(client):
    resp = await client.post(f"/v1/chats/{uuid.uuid4()}/read")
    assert_error(resp, 401, "unauthorized")


async def test_read_chat_without_inbound_is_noop(client, auth_headers, meta):
    await make_contact()
    opened = await client.post("/v1/chats", headers=auth_headers, json={"wa_id": WA_ID})
    resp = await client.post(
        f"/v1/chats/{opened.json()['data']['id']}/read", headers=auth_headers
    )
    assert resp.status_code == 204
    assert meta.read == []


# ---------------------------------------------------------------------------
# replay: messages stored before P6 existed
# ---------------------------------------------------------------------------
async def test_stored_message_event_is_replayed(client, auth_headers):
    from sqlalchemy import text

    from modules.webhook.processor import WebhookProcessor

    message = inbound("wamid.OLDEVENT", ts=int(utcnow().timestamp()))
    async with SessionFactory() as session:
        await session.exec(
            text(
                "INSERT INTO webhook_events (event_key, payload) "
                "VALUES ('msg:wamid.OLDEVENT', CAST(:p AS jsonb))"
            ),
            params={
                "p": json.dumps(
                    {
                        "kind": "message",
                        "message": message,
                        "contacts": [{"profile": {"name": "Ananya"}, "wa_id": WA_ID}],
                    }
                )
            },
        )
        await session.commit()

    assert await WebhookProcessor().replay_unprocessed() == 1
    chat = await only_chat(client, auth_headers)
    assert chat["last_message"]["timestamp"] == message["timestamp"]
    assert to_unix_str(utcnow()) >= chat["last_message"]["timestamp"]

import json
from datetime import timedelta

import pytest
from sqlalchemy import text

from config.app_config import app_config
from core.database import SessionFactory
from core.time import utcnow
from modules.messages.models import MessageStatus
from modules.webhook.processor import WebhookProcessor
from modules.webhook.signature import compute_signature
from tests.factories import (
    assert_error,
    count,
    get_message,
    make_open_chat,
    make_outbound,
)

CHALLENGE = "1158201444"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def envelope(phone_number_id: str, **value) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550000000",
                                "phone_number_id": phone_number_id,
                            },
                            **value,
                        },
                    }
                ],
            }
        ],
    }


def status_item(wamid: str, status: str, **extra) -> dict:
    return {
        "id": wamid,
        "status": status,
        "timestamp": "1758067200",
        "recipient_id": "919820011223",
        **extra,
    }


async def post_signed(client, payload: dict | bytes, signature: str | None = None):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    headers["X-Hub-Signature-256"] = signature or compute_signature(body)
    return await client.post("/webhook", content=body, headers=headers)


async def post_statuses(client, business, *statuses: dict):
    payload = envelope(business.phone_number_id, statuses=list(statuses))
    resp = await post_signed(client, payload)
    assert resp.status_code == 200, resp.text
    return resp


async def event_rows() -> dict[str, bool]:
    """event_key -> processed?"""
    async with SessionFactory() as session:
        rows = await session.exec(
            text("SELECT event_key, processed_at FROM webhook_events")
        )
        return {r.event_key: r.processed_at is not None for r in rows}


# ---------------------------------------------------------------------------
# GET /webhook handshake
# ---------------------------------------------------------------------------
async def test_handshake_echoes_challenge(client):
    resp = await client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": app_config.meta_verify_token.get_secret_value(),
            "hub.challenge": CHALLENGE,
        },
    )
    assert resp.status_code == 200
    assert resp.text == CHALLENGE
    assert resp.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "params",
    [
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
        {"hub.mode": "unsubscribe", "hub.verify_token": "TOKEN", "hub.challenge": "1"},
        {"hub.mode": "subscribe", "hub.verify_token": "TOKEN"},
        {},
    ],
    ids=["wrong-token", "wrong-mode", "no-challenge", "no-params"],
)
async def test_handshake_rejected(client, params):
    if params.get("hub.verify_token") == "TOKEN":
        params["hub.verify_token"] = app_config.meta_verify_token.get_secret_value()
    resp = await client.get("/webhook", params=params)
    assert_error(resp, 403, "forbidden")


async def test_webhook_needs_no_jwt(client, business):
    """Meta can't send our JWT — the signature is the auth."""
    resp = await post_signed(client, envelope(business.phone_number_id))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /webhook — signature + persistence
# ---------------------------------------------------------------------------
async def test_missing_signature_is_403(client, business):
    body = json.dumps(
        envelope(business.phone_number_id, statuses=[status_item("w1", "sent")])
    )
    resp = await client.post("/webhook", content=body)
    assert_error(resp, 403, "forbidden")
    assert await count("webhook_events") == 0


async def test_bad_signature_is_403(client, business):
    payload = envelope(business.phone_number_id, statuses=[status_item("w1", "sent")])
    resp = await post_signed(client, payload, signature="sha256=" + "0" * 64)
    assert_error(resp, 403, "forbidden")
    assert await count("webhook_events") == 0


async def test_signature_covers_raw_bytes(client, business):
    """Re-serialised JSON (different spacing) must NOT verify."""
    payload = envelope(business.phone_number_id, statuses=[status_item("w1", "sent")])
    signed_for = json.dumps(payload).encode()
    sent = json.dumps(payload, separators=(",", ":")).encode()
    resp = await post_signed(client, sent, signature=compute_signature(signed_for))
    assert_error(resp, 403, "forbidden")


async def test_events_stored_with_keys(client, business):
    payload = envelope(
        business.phone_number_id,
        contacts=[{"profile": {"name": "Ananya"}, "wa_id": "919820011223"}],
        messages=[
            {
                "from": "919820011223",
                "id": "wamid.IN1",
                "timestamp": "1758067200",
                "type": "text",
                "text": {"body": "Hi"},
            }
        ],
        statuses=[status_item("wamid.OUT1", "delivered")],
    )
    resp = await post_signed(client, payload)
    assert resp.status_code == 200
    assert resp.content == b""
    assert set(await event_rows()) == {"msg:wamid.IN1", "status:wamid.OUT1:delivered"}


async def test_redelivery_is_deduplicated(client, business):
    payload = envelope(business.phone_number_id, statuses=[status_item("w1", "sent")])
    await post_signed(client, payload)
    await post_signed(client, payload)
    assert await count("webhook_events") == 1


async def test_other_phone_number_is_ignored(client):
    payload = envelope("SOME-OTHER-NUMBER", statuses=[status_item("w1", "sent")])
    resp = await post_signed(client, payload)
    assert resp.status_code == 200
    assert await count("webhook_events") == 0


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b"{}"])
async def test_garbage_body_with_valid_signature_is_200(client, body):
    resp = await post_signed(client, body)
    assert resp.status_code == 200
    assert await count("webhook_events") == 0


async def test_inbound_message_event_is_processed(client, business):
    payload = envelope(
        business.phone_number_id,
        messages=[
            {
                "from": "919820011223",
                "id": "wamid.IN1",
                "timestamp": "1758067200",
                "type": "text",
                "text": {"body": "Hi"},
            }
        ],
    )
    await post_signed(client, payload)
    assert await event_rows() == {"msg:wamid.IN1": True}
    assert await count("messages") == 1


# ---------------------------------------------------------------------------
# statuses -> message ticks
# ---------------------------------------------------------------------------
async def test_status_updates_message(client, business):
    chat = await make_open_chat()
    msg = await make_outbound(chat, wamid="wamid.A", status=MessageStatus.SENT)

    await post_statuses(client, business, status_item("wamid.A", "delivered"))
    assert (await get_message(msg.id)).status == MessageStatus.DELIVERED

    await post_statuses(client, business, status_item("wamid.A", "read"))
    assert (await get_message(msg.id)).status == MessageStatus.READ
    assert all((await event_rows()).values())


async def test_out_of_order_status_never_downgrades(client, business):
    chat = await make_open_chat()
    msg = await make_outbound(chat, wamid="wamid.A", status=MessageStatus.PENDING)

    # Meta delivers out of order: read first, then a late sent + delivered
    await post_statuses(client, business, status_item("wamid.A", "read"))
    await post_statuses(
        client,
        business,
        status_item("wamid.A", "sent"),
        status_item("wamid.A", "delivered"),
    )
    assert (await get_message(msg.id)).status == MessageStatus.READ
    # the stale ones are still marked processed
    assert all((await event_rows()).values())


async def test_failed_status_stores_error(client, business):
    chat = await make_open_chat()
    msg = await make_outbound(chat, wamid="wamid.A", status=MessageStatus.SENT)
    await post_statuses(
        client,
        business,
        status_item(
            "wamid.A",
            "failed",
            errors=[{"code": 131026, "title": "Message undeliverable"}],
        ),
    )
    stored = await get_message(msg.id)
    assert stored.status == MessageStatus.FAILED
    assert stored.error_code == 131026
    assert stored.error_title == "Message undeliverable"


async def test_unknown_status_label_is_ignored(client, business):
    chat = await make_open_chat()
    msg = await make_outbound(chat, wamid="wamid.A", status=MessageStatus.SENT)
    await post_statuses(client, business, status_item("wamid.A", "deleted"))
    assert (await get_message(msg.id)).status == MessageStatus.SENT
    assert await event_rows() == {"status:wamid.A:deleted": True}


async def test_unmatched_status_waits_then_is_dropped(client, business):
    await post_statuses(client, business, status_item("wamid.NOPE", "delivered"))
    assert await event_rows() == {"status:wamid.NOPE:delivered": False}

    async with SessionFactory() as session:
        await session.exec(
            text("UPDATE webhook_events SET received_at = :t"),
            params={"t": utcnow() - timedelta(hours=2)},
        )
        await session.commit()

    await WebhookProcessor().replay_unprocessed()
    assert await event_rows() == {"status:wamid.NOPE:delivered": True}


async def test_status_arriving_before_send_commit_is_applied(
    client, auth_headers, business
):
    """Meta's 'delivered' can beat our own wamid commit: it waits, then is
    applied as soon as the send stores the wamid."""
    # FakeMeta hands out wamid.fake.1 for the first send
    await post_statuses(client, business, status_item("wamid.fake.1", "delivered"))

    chat = await make_open_chat()
    resp = await client.post(
        f"/v1/chats/{chat.id}/messages",
        headers=auth_headers,
        json={"client_msg_id": "c1", "type": "text", "body": "hi"},
    )
    stored = await get_message(resp.json()["data"]["id"])
    assert stored.wamid == "wamid.fake.1"
    assert stored.status == MessageStatus.DELIVERED
    assert await event_rows() == {"status:wamid.fake.1:delivered": True}


async def test_replay_applies_unprocessed_events(client, business):
    chat = await make_open_chat()
    msg = await make_outbound(chat, wamid="wamid.A", status=MessageStatus.SENT)
    async with SessionFactory() as session:
        await session.exec(
            text(
                "INSERT INTO webhook_events (event_key, payload) "
                "VALUES (:k, CAST(:p AS jsonb))"
            ),
            params={
                "k": "status:wamid.A:read",
                "p": json.dumps(
                    {"kind": "status", "status": status_item("wamid.A", "read")}
                ),
            },
        )
        await session.commit()

    assert await WebhookProcessor().replay_unprocessed() == 1
    assert (await get_message(msg.id)).status == MessageStatus.READ
    assert await event_rows() == {"status:wamid.A:read": True}

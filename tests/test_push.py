"""P8: FCM data-only pushes for inbound messages."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from firebase_admin import exceptions, messaging
from sqlalchemy import text

from config.app_config import app_config
from core.database import SessionFactory
from core.time import utcnow
from integrations.fcm import client as fcm_module
from integrations.fcm.client import FcmClient, get_fcm_client, init_fcm, set_fcm_client
from modules.messages.models import MessageStatus
from tests.factories import WA_ID, count, make_chat, make_open_chat, make_outbound
from tests.test_inbound import deliver, inbound
from tests.test_webhook import post_statuses, status_item

PUSH_KEYS = {"chat_id", "sender_id", "sender_name", "body"}


async def register(client, auth_headers, *tokens: str) -> None:
    for token in tokens:
        resp = await client.post(
            "/v1/me/fcm-token",
            headers=auth_headers,
            json={"token": token, "platform": "android"},
        )
        assert resp.status_code == 204


async def stored_tokens() -> set[str]:
    async with SessionFactory() as session:
        rows = await session.exec(text("SELECT token FROM fcm_tokens"))
        return {r.token for r in rows}


async def chat_id_for(wa_id: str = WA_ID) -> str:
    async with SessionFactory() as session:
        row = await session.exec(
            text("SELECT id FROM chats WHERE contact_wa_id = :w"), params={"w": wa_id}
        )
        return str(row.one().id)


# ---------------------------------------------------------------------------
# when a push is sent
# ---------------------------------------------------------------------------
async def test_inbound_message_pushes_to_every_device(
    client, auth_headers, business, fcm
):
    await register(client, auth_headers, "phone-1", "phone-2")
    await deliver(client, business, inbound("wamid.IN1"), name="Ananya Mehta")

    [(tokens, data)] = fcm.sent
    assert sorted(tokens) == ["phone-1", "phone-2"]
    assert set(data) == PUSH_KEYS
    assert all(isinstance(v, str) for v in data.values())
    assert data == {
        "chat_id": await chat_id_for(),
        "sender_id": WA_ID,
        "sender_name": "Ananya Mehta",
        "body": "Hi there",
    }


async def test_no_push_while_app_is_connected(client, auth_headers, business, fcm, ws):
    await register(client, auth_headers, "phone-1")
    await deliver(client, business, inbound("wamid.IN1"))
    assert fcm.sent == []
    # ...WS delivered it instead
    assert ws.types == ["message.new", "chat.updated"]


async def test_no_push_for_muted_chat(client, auth_headers, business, fcm):
    await register(client, auth_headers, "phone-1")
    await make_chat(is_muted=True)
    await deliver(client, business, inbound("wamid.IN1"))
    assert fcm.sent == []
    assert await count("messages") == 1


async def test_no_push_without_devices(client, business, fcm):
    await deliver(client, business, inbound("wamid.IN1"))
    assert fcm.sent == []


async def test_no_push_for_old_replayed_message(client, auth_headers, business, fcm):
    await register(client, auth_headers, "phone-1")
    old = int((utcnow() - timedelta(hours=3)).timestamp())
    await deliver(client, business, inbound("wamid.IN1", ts=old))
    assert fcm.sent == []
    assert await count("messages") == 1


async def test_no_push_for_duplicate(client, auth_headers, business, fcm):
    await register(client, auth_headers, "phone-1")
    await deliver(client, business, inbound("wamid.IN1"))
    await deliver(client, business, inbound("wamid.IN1"))
    assert len(fcm.sent) == 1


async def test_no_push_for_status_updates(client, auth_headers, business, fcm):
    await register(client, auth_headers, "phone-1")
    chat = await make_open_chat()
    await make_outbound(chat, wamid="wamid.A", status=MessageStatus.SENT)
    await post_statuses(client, business, status_item("wamid.A", "delivered"))
    assert fcm.sent == []


async def test_no_push_when_fcm_disabled(client, auth_headers, business):
    set_fcm_client(None)
    await register(client, auth_headers, "phone-1")
    await deliver(client, business, inbound("wamid.IN1"))
    assert await count("messages") == 1


# ---------------------------------------------------------------------------
# failures + token cleanup
# ---------------------------------------------------------------------------
async def test_dead_tokens_are_deleted(client, auth_headers, business, fcm):
    await register(client, auth_headers, "alive", "uninstalled")
    fcm.dead = {"uninstalled"}
    await deliver(client, business, inbound("wamid.IN1"))
    assert await stored_tokens() == {"alive"}


async def test_push_failure_never_breaks_the_webhook(
    client, auth_headers, business, fcm
):
    await register(client, auth_headers, "phone-1")
    fcm.error = RuntimeError("FCM down")
    await deliver(client, business, inbound("wamid.IN1"))

    assert await count("messages") == 1
    async with SessionFactory() as session:
        processed = await session.exec(
            text("SELECT processed_at IS NOT NULL AS done FROM webhook_events")
        )
        assert processed.one().done
    assert await stored_tokens() == {"phone-1"}


# ---------------------------------------------------------------------------
# notification text
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "content", "expected"),
    [
        ("image", {"id": "m1", "caption": "invoice"}, "📷 Photo: invoice"),
        ("image", {"id": "m1"}, "📷 Photo"),
        ("audio", {"id": "m1"}, "🎵 Audio"),
        ("document", {"id": "m1", "filename": "bill.pdf"}, "📄 Document: bill.pdf"),
        ("location", {"latitude": 1, "longitude": 2}, "📍 Location"),
        ("location", {"latitude": 1, "longitude": 2, "name": "Office"}, "Office"),
    ],
)
async def test_push_body_preview(
    client, auth_headers, business, fcm, kind, content, expected
):
    await register(client, auth_headers, "phone-1")
    await deliver(client, business, inbound("wamid.IN1", kind=kind, content=content))
    [(_, data)] = fcm.sent
    assert data["body"] == expected


# ---------------------------------------------------------------------------
# FcmClient against firebase-admin (the SDK call itself is stubbed)
# ---------------------------------------------------------------------------
def _result(error: Exception | None = None):
    return SimpleNamespace(success=error is None, exception=error)


async def test_fcm_client_sends_data_only_high_priority(monkeypatch):
    calls = []

    def fake_send(message, app=None):
        calls.append(message)
        return SimpleNamespace(
            responses=[_result(), _result()], success_count=2, failure_count=0
        )

    monkeypatch.setattr(messaging, "send_each_for_multicast", fake_send)
    data = {"chat_id": "c", "sender_id": "s", "sender_name": "n", "body": "b"}
    dead = await FcmClient(app=object()).send_data(["t1", "t2"], data)

    assert dead == []
    [message] = calls
    assert message.tokens == ["t1", "t2"]
    assert message.data == data
    assert message.notification is None
    assert message.android.priority == "high"
    assert message.apns.payload.aps.content_available is True


async def test_fcm_client_reports_only_dead_tokens(monkeypatch):
    responses = [
        _result(),
        _result(messaging.UnregisteredError("gone")),
        _result(messaging.SenderIdMismatchError("other project")),
        _result(
            exceptions.InvalidArgumentError(
                "The registration token is not a valid FCM registration token"
            )
        ),
        _result(exceptions.UnavailableError("try later")),
        _result(exceptions.InvalidArgumentError("bad payload")),
    ]
    monkeypatch.setattr(
        messaging,
        "send_each_for_multicast",
        lambda message, app=None: SimpleNamespace(
            responses=responses, success_count=1, failure_count=5
        ),
    )
    tokens = ["ok", "unreg", "mismatch", "invalid", "busy", "payload"]
    dead = await FcmClient(app=object()).send_data(tokens, {"body": "x"})
    assert dead == ["unreg", "mismatch", "invalid"]


async def test_fcm_client_batches_500(monkeypatch):
    sizes = []

    def fake_send(message, app=None):
        sizes.append(len(message.tokens))
        n = len(message.tokens)
        return SimpleNamespace(
            responses=[_result()] * n, success_count=n, failure_count=0
        )

    monkeypatch.setattr(messaging, "send_each_for_multicast", fake_send)
    await FcmClient(app=object()).send_data([f"t{i}" for i in range(1001)], {})
    assert sizes == [500, 500, 1]


# ---------------------------------------------------------------------------
# init_fcm
# ---------------------------------------------------------------------------
def test_init_without_credentials_disables_push(monkeypatch):
    monkeypatch.setattr(app_config, "firebase_credentials", None)
    init_fcm()
    assert get_fcm_client() is None


def test_init_with_missing_file_fails_startup(monkeypatch, tmp_path):
    monkeypatch.setattr(fcm_module, "FIREBASE_APP_NAME", "equitycase-test-missing")
    monkeypatch.setattr(
        app_config, "firebase_credentials", str(tmp_path / "missing.json")
    )
    with pytest.raises(RuntimeError):
        init_fcm()

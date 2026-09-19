"""MetaClient against a mocked transport — no network."""

import json

import httpx
import pytest

from config.app_config import app_config
from integrations.meta.client import MetaClient
from integrations.meta.errors import MetaApiError

OK = {"messages": [{"id": "wamid.OK"}]}


def make_client(responses: list) -> tuple[MetaClient, list[httpx.Request]]:
    """Each item is a status code, (status, json) or an exception to raise."""
    calls: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        status, payload = item if isinstance(item, tuple) else (item, {})
        return httpx.Response(status, json=payload)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MetaClient(http, backoff_seconds=0), calls


async def send(client: MetaClient, **kw) -> str:
    return await client.send_text(
        phone_number_id="PNID", to="919820011223", **kw, body="Hi"
    )


async def test_send_text_payload_and_auth():
    client, calls = make_client([(200, OK)])
    assert await send(client, reply_to_wamid="wamid.parent") == "wamid.OK"

    [req] = calls
    assert req.method == "POST"
    assert req.url.path == f"/{app_config.meta_api_version}/PNID/messages"
    token = app_config.meta_access_token.get_secret_value()
    assert req.headers["Authorization"] == f"Bearer {token}"
    assert json.loads(req.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "919820011223",
        "type": "text",
        "text": {"preview_url": True, "body": "Hi"},
        "context": {"message_id": "wamid.parent"},
    }


async def test_retries_5xx_then_succeeds():
    client, calls = make_client([500, 503, (200, OK)])
    assert await send(client) == "wamid.OK"
    assert len(calls) == 3


async def test_429_gives_up_after_three_attempts():
    client, calls = make_client([429, 429, 429])
    with pytest.raises(MetaApiError) as e:
        await send(client)
    assert e.value.http_status == 429
    assert len(calls) == 3


async def test_4xx_is_not_retried_and_parsed():
    error = {
        "error": {
            "message": "(#131047) Re-engagement message",
            "code": 131047,
        }
    }
    client, calls = make_client([(400, error)])
    with pytest.raises(MetaApiError) as e:
        await send(client)
    assert len(calls) == 1
    assert e.value.code == 131047
    assert e.value.title == "(#131047) Re-engagement message"
    assert e.value.is_window_closed


async def test_connect_error_is_retried():
    client, calls = make_client([httpx.ConnectError("down"), (200, OK)])
    assert await send(client) == "wamid.OK"
    assert len(calls) == 2


async def test_read_timeout_is_not_retried():
    """Meta may have received it — a retry could double-send."""
    client, calls = make_client([httpx.ReadTimeout("slow")])
    with pytest.raises(MetaApiError):
        await send(client)
    assert len(calls) == 1


async def test_unexpected_success_body():
    client, _ = make_client([(200, {"weird": True})])
    with pytest.raises(MetaApiError):
        await send(client)


async def test_mark_read_payload():
    client, calls = make_client([(200, {"success": True})])
    await client.mark_read(phone_number_id="PNID", wamid="wamid.IN")
    [req] = calls
    assert req.url.path == f"/{app_config.meta_api_version}/PNID/messages"
    assert json.loads(req.content) == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.IN",
    }

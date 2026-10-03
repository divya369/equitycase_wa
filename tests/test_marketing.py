"""Marketing opt-outs: the STOP button, and the API the blast CLI calls."""

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from config.app_config import app_config
from core.database import SessionFactory
from modules.marketing.service import is_stop_request
from tests.factories import WA_ID, assert_error
from tests.test_inbound import deliver, inbound

API_KEY = "test-marketing-key"
OPT_OUT_KEYS = {"wa_id", "opted_out", "source", "created_at"}


@pytest.fixture(autouse=True)
def marketing_key(monkeypatch):
    monkeypatch.setattr(app_config, "marketing_api_key", SecretStr(API_KEY))


@pytest.fixture
def key_headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


async def opt_out_rows() -> list[tuple[str, str]]:
    async with SessionFactory() as session:
        rows = await session.exec(
            text("SELECT wa_id, source FROM marketing_opt_outs ORDER BY wa_id")
        )
        return [(r.wa_id, r.source) for r in rows]


def button_message(wamid: str, text_value: str = "STOP") -> dict:
    """What Meta sends when a quick-reply button under a template is tapped."""
    return {
        "from": WA_ID,
        "id": wamid,
        "timestamp": "1700000000",
        "type": "button",
        "button": {"text": text_value, "payload": text_value},
    }


# ---------------------------------------------------------------------------
# recognising a stop request
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "body", ["STOP", "stop", " Stop. ", "unsubscribe", "Opt out", "STOPALL"]
)
def test_stop_words_are_recognised(body):
    assert is_stop_request(body)


@pytest.mark.parametrize(
    "body",
    ["please stop sending these", "stopwatch", "", "I want to stop my SIP", "start"],
)
def test_other_text_is_not_a_stop_request(body):
    assert not is_stop_request(body)


# ---------------------------------------------------------------------------
# the webhook records it
# ---------------------------------------------------------------------------
async def test_stop_button_opts_the_number_out(client, business):
    await deliver(client, business, button_message("wamid.STOP1"))
    assert await opt_out_rows() == [(WA_ID, "stop_button")]


async def test_typed_stop_opts_the_number_out(client, business):
    await deliver(client, business, inbound("wamid.STOP2", content={"body": "STOP"}))
    assert await opt_out_rows() == [(WA_ID, "stop_text")]


async def test_stop_button_is_still_stored_as_a_message(client, auth_headers, business):
    await deliver(client, business, button_message("wamid.STOP3"))

    chats = (await client.get("/v1/chats", headers=auth_headers)).json()["data"]
    assert chats[0]["last_message"]["text"]["body"] == "STOP"


async def test_ordinary_message_does_not_opt_out(client, business):
    await deliver(client, business, inbound("wamid.IN1"))
    assert await opt_out_rows() == []


async def test_second_stop_keeps_one_row(client, business):
    await deliver(client, business, button_message("wamid.STOP4"))
    await deliver(client, business, button_message("wamid.STOP5"))
    assert await opt_out_rows() == [(WA_ID, "stop_button")]


# ---------------------------------------------------------------------------
# the API the CLI calls
# ---------------------------------------------------------------------------
async def test_status_is_false_for_an_unknown_number(client, key_headers):
    resp = await client.get("/v1/marketing/number/+919820011223", headers=key_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"data", "meta"}
    assert set(body["data"]) == OPT_OUT_KEYS
    assert body["data"] == {
        "wa_id": "919820011223",
        "opted_out": False,
        "source": None,
        "created_at": None,
    }


async def test_status_is_true_after_a_stop(client, business, key_headers):
    await deliver(client, business, button_message("wamid.STOP6"))

    resp = await client.get(f"/v1/marketing/number/{WA_ID}", headers=key_headers)
    data = resp.json()["data"]
    assert data["opted_out"] is True
    assert data["source"] == "stop_button"
    assert data["created_at"] is not None


async def test_manual_opt_out_and_opt_in(client, key_headers):
    phone = "+919820011223"
    assert (
        await client.post(f"/v1/marketing/number/{phone}/opt-out", headers=key_headers)
    ).status_code == 204
    assert await opt_out_rows() == [("919820011223", "manual")]

    resp = await client.get(f"/v1/marketing/number/{phone}", headers=key_headers)
    assert resp.json()["data"]["opted_out"] is True

    assert (
        await client.delete(
            f"/v1/marketing/number/{phone}/opt-out", headers=key_headers
        )
    ).status_code == 204
    assert await opt_out_rows() == []


async def test_opt_out_list(client, business, key_headers):
    await deliver(client, business, button_message("wamid.STOP7"))
    await client.post("/v1/marketing/number/+919820011224/opt-out", headers=key_headers)

    data = (await client.get("/v1/marketing/opt-outs", headers=key_headers)).json()[
        "data"
    ]
    assert {row["wa_id"] for row in data} == {WA_ID, "919820011224"}
    assert all(row["opted_out"] for row in data)


# ---------------------------------------------------------------------------
# the key guards every route
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/v1/marketing/number/+919820011223"),
        ("get", "/v1/marketing/opt-outs"),
        ("post", "/v1/marketing/number/+919820011223/opt-out"),
        ("delete", "/v1/marketing/number/+919820011223/opt-out"),
    ],
)
async def test_routes_need_the_api_key(client, method, path):
    assert_error(await getattr(client, method)(path), 401, "unauthorized")


async def test_wrong_api_key_is_rejected(client):
    resp = await client.get(
        "/v1/marketing/number/+919820011223", headers={"X-API-Key": "nope"}
    )
    assert_error(resp, 401, "unauthorized")


async def test_routes_are_closed_when_no_key_is_configured(
    client, key_headers, monkeypatch
):
    monkeypatch.setattr(app_config, "marketing_api_key", None)
    assert_error(
        await client.get("/v1/marketing/number/+919820011223", headers=key_headers),
        401,
        "unauthorized",
    )


async def test_operator_jwt_is_not_accepted_here(client, auth_headers):
    """These routes take the shared key only — not the operator token."""
    assert_error(
        await client.get("/v1/marketing/number/+919820011223", headers=auth_headers),
        401,
        "unauthorized",
    )

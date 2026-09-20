"""P12: several operators, one shared inbox.

Push rule: an operator on a WebSocket already saw the message, so only the
others' devices get one.
"""

from datetime import timedelta

import jwt
import pytest
from sqlalchemy import text

from config.app_config import app_config
from core.database import SessionFactory
from core.time import utcnow
from modules.operator.repository import OperatorRepository
from realtime.manager import ws_manager
from tests.conftest import RecordingSocket
from tests.factories import assert_error
from tests.test_inbound import deliver, inbound
from tests.test_push import register


async def fcm_rows() -> list[tuple[str, int]]:
    async with SessionFactory() as session:
        rows = await session.exec(
            text("SELECT token, operator_id FROM fcm_tokens ORDER BY token")
        )
        return [(r.token, r.operator_id) for r in rows]


# ---------------------------------------------------------------------------
# who may log in
# ---------------------------------------------------------------------------
async def test_second_operator_can_request_and_verify_otp(
    client, second_operator, sent_codes
):
    resp = await client.post(
        "/v1/auth/otp/request", json={"phone": second_operator.phone}
    )
    assert resp.status_code == 204
    [(phone, code)] = sent_codes
    assert phone == second_operator.phone

    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": second_operator.phone, "code": code}
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["user"]["name"] == "Second Operator"

    # the token identifies THEM, not the seeded operator
    me = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert me.json()["data"]["wa_id"] == second_operator.wa_id


async def test_both_operators_can_have_a_code_at_once(
    client, operator, second_operator, sent_codes
):
    await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    await client.post("/v1/auth/otp/request", json={"phone": second_operator.phone})
    (_, first_code), (_, second_code) = sent_codes

    # the second request must NOT have invalidated the first operator's code
    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": operator.phone, "code": first_code}
    )
    assert resp.status_code == 200
    resp = await client.post(
        "/v1/auth/otp/verify",
        json={"phone": second_operator.phone, "code": second_code},
    )
    assert resp.status_code == 200


async def test_unknown_phone_still_gets_204_and_no_sms(client, sent_codes):
    resp = await client.post("/v1/auth/otp/request", json={"phone": "+919111100000"})
    assert resp.status_code == 204
    assert sent_codes == []


async def test_other_operators_code_is_rejected(
    client, operator, second_operator, sent_codes
):
    await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    [(_, code)] = sent_codes

    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": second_operator.phone, "code": code}
    )
    assert_error(resp, 401, "invalid_otp")


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------
async def test_token_of_removed_operator_is_unauthorized(
    client, second_operator, headers_for
):
    headers = headers_for(second_operator.id)
    assert (await client.get("/v1/me", headers=headers)).status_code == 200

    async with SessionFactory() as session:
        repo = OperatorRepository(session)
        await repo.delete(await repo.get(second_operator.id))
        await session.commit()

    assert_error(await client.get("/v1/me", headers=headers), 401, "unauthorized")


async def test_pre_p12_token_still_works(client, operator):
    """Phones logged in before P12 carry sub="operator"."""
    now = utcnow()
    legacy = jwt.encode(
        {"sub": "operator", "iat": now, "exp": now + timedelta(hours=1)},
        app_config.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    resp = await client.get("/v1/me", headers={"Authorization": f"Bearer {legacy}"})
    assert resp.json()["data"]["wa_id"] == operator.wa_id


@pytest.mark.parametrize("subject", ["operator:", "operator:abc", "admin:1", "1"])
async def test_broken_subject_is_rejected(client, subject):
    now = utcnow()
    token = jwt.encode(
        {"sub": subject, "iat": now, "exp": now + timedelta(hours=1)},
        app_config.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    assert_error(
        await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"}),
        401,
        "unauthorized",
    )


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------
async def test_device_belongs_to_the_operator_that_registered_it(
    client, auth_headers, second_operator, headers_for
):
    await register(client, auth_headers, "phone-1")
    await register(client, headers_for(second_operator.id), "phone-2")
    assert await fcm_rows() == [("phone-1", 1), ("phone-2", second_operator.id)]


async def test_device_moves_when_someone_else_logs_in_on_it(
    client, auth_headers, second_operator, headers_for
):
    await register(client, auth_headers, "shared-phone")
    await register(client, headers_for(second_operator.id), "shared-phone")
    assert await fcm_rows() == [("shared-phone", second_operator.id)]


# ---------------------------------------------------------------------------
# push routing — the point of P12
# ---------------------------------------------------------------------------
async def test_push_goes_only_to_operators_without_a_socket(
    client, auth_headers, second_operator, headers_for, business, fcm, ws
):
    """`ws` is the seeded operator's socket; the second operator is away."""
    await register(client, auth_headers, "phone-1")
    await register(client, headers_for(second_operator.id), "phone-2")

    await deliver(client, business, inbound("wamid.IN1"))

    [(tokens, _)] = fcm.sent
    assert tokens == ["phone-2"]
    # the watching operator got it live instead
    assert ws.types == ["message.new", "chat.updated"]


async def test_no_push_when_every_operator_is_watching(
    client, auth_headers, second_operator, headers_for, business, fcm, ws
):
    await register(client, auth_headers, "phone-1")
    await register(client, headers_for(second_operator.id), "phone-2")
    second_socket = RecordingSocket()
    ws_manager.add(second_socket, second_operator.id)

    await deliver(client, business, inbound("wamid.IN1"))

    assert fcm.sent == []
    assert second_socket.types == ["message.new", "chat.updated"]


async def test_push_reaches_everyone_when_nobody_is_watching(
    client, auth_headers, second_operator, headers_for, business, fcm
):
    await register(client, auth_headers, "phone-1")
    await register(client, headers_for(second_operator.id), "phone-2")

    await deliver(client, business, inbound("wamid.IN1"))

    [(tokens, _)] = fcm.sent
    assert sorted(tokens) == ["phone-1", "phone-2"]


async def test_second_operators_second_device_also_gets_the_push(
    client, auth_headers, second_operator, headers_for, business, fcm, ws
):
    headers = headers_for(second_operator.id)
    await register(client, auth_headers, "phone-1")
    await register(client, headers, "phone-2", "tablet-2")

    await deliver(client, business, inbound("wamid.IN1"))

    [(tokens, _)] = fcm.sent
    assert sorted(tokens) == ["phone-2", "tablet-2"]


# ---------------------------------------------------------------------------
# the shared inbox itself
# ---------------------------------------------------------------------------
async def test_both_operators_see_the_same_chats(
    client, auth_headers, second_operator, headers_for, business
):
    await deliver(client, business, inbound("wamid.IN1"))

    mine = await client.get("/v1/chats", headers=auth_headers)
    theirs = await client.get("/v1/chats", headers=headers_for(second_operator.id))
    assert mine.json()["data"] == theirs.json()["data"]
    assert len(mine.json()["data"]) == 1


async def test_read_by_one_operator_clears_it_for_the_other(
    client, auth_headers, second_operator, headers_for, business
):
    await deliver(client, business, inbound("wamid.IN1"))
    chat_id = (await client.get("/v1/chats", headers=auth_headers)).json()["data"][0][
        "id"
    ]

    resp = await client.post(f"/v1/chats/{chat_id}/read", headers=auth_headers)
    assert resp.status_code == 204

    theirs = await client.get("/v1/chats", headers=headers_for(second_operator.id))
    assert theirs.json()["data"][0]["unread_count"] == 0

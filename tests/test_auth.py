from datetime import timedelta

import jwt
from sqlalchemy import text

from config.app_config import app_config
from core.database import SessionFactory
from core.time import utcnow

USER_KEYS = {"wa_id", "name", "phone", "avatar_url", "about", "is_online", "last_seen"}


async def _otp_rows() -> list[dict]:
    async with SessionFactory() as session:
        rows = await session.exec(
            text("SELECT attempts, consumed_at FROM otp_codes ORDER BY id")
        )
        return [dict(r._mapping) for r in rows]


def _assert_error(resp, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"errors"}
    assert body["errors"]["code"] == code
    assert body["errors"]["request_id"]


# ---------------------------------------------------------------------------
# otp/request
# ---------------------------------------------------------------------------
async def test_request_unknown_phone_is_204_and_sends_nothing(client, sent_codes):
    resp = await client.post("/v1/auth/otp/request", json={"phone": "+15550000000"})
    assert resp.status_code == 204
    assert resp.content == b""
    assert sent_codes == []
    assert await _otp_rows() == []


async def test_request_known_phone_stores_hash_and_sends(client, operator, sent_codes):
    resp = await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    assert resp.status_code == 204

    assert len(sent_codes) == 1
    phone, code = sent_codes[0]
    assert phone == operator.phone
    assert len(code) == 6 and code.isdigit()

    async with SessionFactory() as session:
        stored = (await session.exec(text("SELECT code_hash FROM otp_codes"))).one()
    assert stored.code_hash.startswith("$argon2")
    assert code not in stored.code_hash


async def test_request_accepts_formatted_phone(client, operator, sent_codes):
    digits = operator.wa_id
    formatted = f"+{digits[:2]} {digits[2:7]} {digits[7:]}"
    resp = await client.post("/v1/auth/otp/request", json={"phone": formatted})
    assert resp.status_code == 204
    assert len(sent_codes) == 1


async def test_request_invalid_phone_is_422(client):
    resp = await client.post("/v1/auth/otp/request", json={"phone": "abc"})
    _assert_error(resp, 422, "validation_error")


# ---------------------------------------------------------------------------
# otp/verify
# ---------------------------------------------------------------------------
async def test_verify_success_returns_token_and_user(client, operator, sent_codes):
    await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    code = sent_codes[0][1]

    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": operator.phone, "code": code}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"data", "meta"}
    assert body["meta"]["request_id"]

    data = body["data"]
    assert set(data) == {"token", "user"}
    assert set(data["user"]) == USER_KEYS
    assert data["user"]["wa_id"] == operator.wa_id
    assert data["user"]["is_online"] is False
    assert data["user"]["last_seen"] is None

    claims = jwt.decode(
        data["token"],
        app_config.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
    )
    assert claims["sub"] == "operator"

    rows = await _otp_rows()
    assert rows[0]["attempts"] == 1
    assert rows[0]["consumed_at"] is not None


async def test_verify_code_cannot_be_reused(client, operator, sent_codes):
    await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    payload = {"phone": operator.phone, "code": sent_codes[0][1]}

    assert (await client.post("/v1/auth/otp/verify", json=payload)).status_code == 200
    resp = await client.post("/v1/auth/otp/verify", json=payload)
    _assert_error(resp, 401, "invalid_otp")


async def test_verify_wrong_code_counts_attempt(client, operator, sent_codes):
    await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    wrong = "000000" if sent_codes[0][1] != "000000" else "111111"

    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": operator.phone, "code": wrong}
    )
    _assert_error(resp, 401, "invalid_otp")
    assert (await _otp_rows())[0]["attempts"] == 1


async def test_code_dies_after_five_attempts(client, operator, sent_codes):
    await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    code = sent_codes[0][1]
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(4):
        await client.post(
            "/v1/auth/otp/verify", json={"phone": operator.phone, "code": wrong}
        )
    # rate limit is 5/minute per IP — reset so we test the attempt cap, not it
    from core.rate_limit import limiter

    limiter.reset()
    await client.post(
        "/v1/auth/otp/verify", json={"phone": operator.phone, "code": wrong}
    )

    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": operator.phone, "code": code}
    )
    _assert_error(resp, 401, "invalid_otp")
    assert (await _otp_rows())[0]["attempts"] == 5


async def test_new_request_invalidates_previous_code(client, operator, sent_codes):
    await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    old, new = sent_codes[0][1], sent_codes[1][1]

    if old != new:
        resp = await client.post(
            "/v1/auth/otp/verify", json={"phone": operator.phone, "code": old}
        )
        _assert_error(resp, 401, "invalid_otp")

    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": operator.phone, "code": new}
    )
    assert resp.status_code == 200


async def test_expired_code_is_rejected(client, operator, sent_codes):
    await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    async with SessionFactory() as session:
        await session.exec(
            text("UPDATE otp_codes SET expires_at = :t"),
            params={"t": utcnow() - timedelta(seconds=1)},
        )
        await session.commit()

    resp = await client.post(
        "/v1/auth/otp/verify",
        json={"phone": operator.phone, "code": sent_codes[0][1]},
    )
    _assert_error(resp, 401, "invalid_otp")


async def test_verify_unknown_phone_is_401(client):
    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": "+15550000000", "code": "123456"}
    )
    _assert_error(resp, 401, "invalid_otp")


# ---------------------------------------------------------------------------
# DEV_STATIC_OTP
# ---------------------------------------------------------------------------
async def test_dev_static_otp_login(client, operator, sent_codes, dev_static_otp):
    resp = await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    assert resp.status_code == 204
    assert sent_codes == []
    assert await _otp_rows() == []

    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": operator.phone, "code": "000000"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["token"]


async def test_dev_static_otp_rejects_other_codes(client, operator, dev_static_otp):
    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": operator.phone, "code": "123456"}
    )
    _assert_error(resp, 401, "invalid_otp")


async def test_static_000000_rejected_when_dev_otp_unset(client, operator):
    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": operator.phone, "code": "000000"}
    )
    _assert_error(resp, 401, "invalid_otp")


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
async def test_otp_request_rate_limited(client, sent_codes):
    for _ in range(5):
        resp = await client.post("/v1/auth/otp/request", json={"phone": "+15550000000"})
        assert resp.status_code == 204

    resp = await client.post("/v1/auth/otp/request", json={"phone": "+15550000000"})
    _assert_error(resp, 429, "rate_limited")


async def test_otp_verify_rate_limited(client):
    for _ in range(5):
        await client.post(
            "/v1/auth/otp/verify", json={"phone": "+15550000000", "code": "123456"}
        )
    resp = await client.post(
        "/v1/auth/otp/verify", json={"phone": "+15550000000", "code": "123456"}
    )
    _assert_error(resp, 429, "rate_limited")


# ---------------------------------------------------------------------------
# logout
# ---------------------------------------------------------------------------
async def test_logout_is_204(client):
    resp = await client.post("/v1/auth/logout")
    assert resp.status_code == 204
    assert resp.content == b""

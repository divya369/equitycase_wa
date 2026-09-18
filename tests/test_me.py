from datetime import timedelta

import jwt
import pytest
from sqlalchemy import text

from config.app_config import app_config
from core.database import SessionFactory
from core.time import utcnow
from modules.operator.repository import OperatorRepository

USER_KEYS = {"wa_id", "name", "phone", "avatar_url", "about", "is_online", "last_seen"}


def _token(**overrides) -> str:
    now = utcnow()
    claims = {"sub": "operator", "iat": now, "exp": now + timedelta(hours=1)}
    claims.update(overrides)
    return jwt.encode(
        claims, app_config.jwt_secret.get_secret_value(), algorithm="HS256"
    )


async def _fcm_rows() -> list[dict]:
    async with SessionFactory() as session:
        rows = await session.exec(
            text("SELECT token, platform FROM fcm_tokens ORDER BY id")
        )
        return [dict(r._mapping) for r in rows]


@pytest.fixture
async def restore_operator_name(operator):
    yield
    async with SessionFactory() as session:
        repo = OperatorRepository(session)
        await repo.update_name(await repo.get(), operator.name)
        await session.commit()


# ---------------------------------------------------------------------------
# JWT enforcement
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic abc"},
        {"Authorization": f"Bearer {_token(sub='someone-else')}"},
        {"Authorization": f"Bearer {_token(exp=utcnow() - timedelta(seconds=1))}"},
    ],
    ids=["missing", "garbage", "not-bearer", "wrong-sub", "expired"],
)
async def test_me_requires_valid_jwt(client, headers):
    resp = await client.get("/v1/me", headers=headers)
    assert resp.status_code == 401, resp.text
    assert resp.json()["errors"]["code"] == "unauthorized"


async def test_token_signed_with_other_secret_rejected(client):
    now = utcnow()
    forged = jwt.encode(
        {"sub": "operator", "iat": now, "exp": now + timedelta(hours=1)},
        "x" * 64,
        algorithm="HS256",
    )
    resp = await client.get("/v1/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET / PATCH /v1/me
# ---------------------------------------------------------------------------
async def test_get_me(client, auth_headers, operator):
    resp = await client.get("/v1/me", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"data", "meta"}
    assert set(body["data"]) == USER_KEYS
    assert body["data"]["wa_id"] == operator.wa_id
    assert body["data"]["phone"] == operator.phone
    assert body["data"]["is_online"] is False
    assert body["data"]["last_seen"] is None
    # null keys are kept, not dropped
    assert "avatar_url" in body["data"]


async def test_patch_me_updates_name(client, auth_headers, restore_operator_name):
    resp = await client.patch(
        "/v1/me", headers=auth_headers, json={"name": "  Test Name  "}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Test Name"

    resp = await client.get("/v1/me", headers=auth_headers)
    assert resp.json()["data"]["name"] == "Test Name"


@pytest.mark.parametrize("body", [{"name": ""}, {"name": "   "}, {}])
async def test_patch_me_validates(client, auth_headers, body):
    resp = await client.patch("/v1/me", headers=auth_headers, json=body)
    assert resp.status_code == 422
    assert resp.json()["errors"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# FCM tokens
# ---------------------------------------------------------------------------
async def test_fcm_token_upsert_and_delete(client, auth_headers):
    body = {"token": "device-token-1", "platform": "android"}
    resp = await client.post("/v1/me/fcm-token", headers=auth_headers, json=body)
    assert resp.status_code == 204

    # same token again (e.g. platform change) -> still one row, updated
    body["platform"] = "ios"
    resp = await client.post("/v1/me/fcm-token", headers=auth_headers, json=body)
    assert resp.status_code == 204
    assert await _fcm_rows() == [{"token": "device-token-1", "platform": "ios"}]

    resp = await client.request(
        "DELETE",
        "/v1/me/fcm-token",
        headers=auth_headers,
        json={"token": "device-token-1"},
    )
    assert resp.status_code == 204
    assert await _fcm_rows() == []


async def test_fcm_token_invalid_platform(client, auth_headers):
    resp = await client.post(
        "/v1/me/fcm-token",
        headers=auth_headers,
        json={"token": "t", "platform": "windows"},
    )
    assert resp.status_code == 422


async def test_fcm_token_requires_jwt(client):
    resp = await client.post(
        "/v1/me/fcm-token", json={"token": "t", "platform": "android"}
    )
    assert resp.status_code == 401

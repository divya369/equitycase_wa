"""Test harness.

Runs against a SEPARATE database (<POSTGRES_DB>_test in the same docker
Postgres) that is created, migrated and seeded once per test session. The
DATABASE_URL override must happen before any app module is imported, because
config and the engine are built at import time.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
_env = dotenv_values(ROOT / ".env")
_dev_url = make_url(os.environ.get("DATABASE_URL") or _env["DATABASE_URL"])
_test_db = f"{_dev_url.database}_test"
TEST_DATABASE_URL = _dev_url.set(database=_test_db).render_as_string(
    hide_password=False
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"] = "test"


async def _create_test_database() -> None:
    import asyncpg

    conn = await asyncpg.connect(
        user=_dev_url.username,
        password=_dev_url.password,
        host=_dev_url.host,
        port=_dev_url.port or 5432,
        database=_dev_url.database,
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _test_db
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_test_db}"')
    finally:
        await conn.close()


def _prepare_database() -> None:
    asyncio.run(_create_test_database())
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    for cmd in (
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [sys.executable, "-m", "scripts.seed"],
    ):
        result = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"{cmd} failed:\n{result.stdout}\n{result.stderr}")


_prepare_database()

# App imports only AFTER DATABASE_URL points at the test database.
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from config.app_config import app_config  # noqa: E402
from core.database import SessionFactory  # noqa: E402
from core.rate_limit import limiter  # noqa: E402
from core.security import create_access_token  # noqa: E402
from integrations.meta.dependencies import get_meta_client  # noqa: E402
from main import app  # noqa: E402
from modules.business.repository import BusinessRepository  # noqa: E402
from modules.operator.repository import OperatorRepository  # noqa: E402

# Tables tests may write to; the seeded singletons are left alone.
_MUTABLE_TABLES = (
    "otp_codes",
    "fcm_tokens",
    "contacts",
    "chats",
    "messages",
    "webhook_events",
)


@pytest.fixture(autouse=True)
async def _clean_state():
    limiter.reset()
    async with SessionFactory() as session:
        await session.exec(
            text(f"TRUNCATE {', '.join(_MUTABLE_TABLES)} RESTART IDENTITY")
        )
        await session.commit()
    yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def operator():
    async with SessionFactory() as session:
        return await OperatorRepository(session).get()


@pytest.fixture
async def business():
    async with SessionFactory() as session:
        return await BusinessRepository(session).get()


class FakeMeta:
    """Stands in for MetaClient. Set `.error` to make the next sends raise."""

    def __init__(self):
        self.sent: list[dict] = []
        self.error: Exception | None = None

    async def send_text(self, *, phone_number_id, to, body, reply_to_wamid=None):
        self.sent.append(
            {
                "phone_number_id": phone_number_id,
                "to": to,
                "body": body,
                "reply_to_wamid": reply_to_wamid,
            }
        )
        if self.error is not None:
            raise self.error
        return f"wamid.fake.{len(self.sent)}"


@pytest.fixture(autouse=True)
def meta():
    """Every test gets a fake Meta client — tests never call the real API."""
    fake = FakeMeta()
    app.dependency_overrides[get_meta_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_meta_client, None)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token()}"}


@pytest.fixture
def dev_static_otp(monkeypatch):
    """Enable DEV_STATIC_OTP=000000 for one test."""
    from pydantic import SecretStr

    monkeypatch.setattr(app_config, "dev_static_otp", SecretStr("000000"))


@pytest.fixture(autouse=True)
def _no_dev_static_otp(request, monkeypatch):
    """Default: real OTP flow, whatever .env says."""
    if "dev_static_otp" not in request.fixturenames:
        monkeypatch.setattr(app_config, "dev_static_otp", None)


@pytest.fixture
def sent_codes(monkeypatch) -> list[tuple[str, str]]:
    """Capture OTPs instead of sending SMS. Items are (phone, code)."""
    sent: list[tuple[str, str]] = []

    class CapturingSender:
        async def send_otp(self, *, phone: str, code: str) -> None:
            sent.append((phone, code))

    monkeypatch.setattr(
        "modules.auth.dependencies.get_otp_sender", lambda: CapturingSender()
    )
    return sent

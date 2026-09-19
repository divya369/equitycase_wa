from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from config.app_config import app_config
from core.database import SessionFactory, engine
from integrations.meta.client import MetaClient, create_http_client
from modules.business.models import BusinessNumber
from modules.business.repository import BusinessRepository
from modules.operator.repository import OperatorRepository
from modules.webhook.processor import WebhookProcessor

logger = structlog.get_logger("lifespan")


def _check_dev_static_otp() -> None:
    if app_config.dev_static_otp is None:
        return

    if app_config.is_production:
        raise RuntimeError("DEV_STATIC_OTP must be unset in production")

    logger.warning(
        "!!! DEV_STATIC_OTP IS SET — any login accepts the static code. "
        "NEVER deploy with this enabled !!!"
    )


async def _load_seeded_rows() -> BusinessNumber:
    """Fail fast: the app is useless without the seeded singleton rows."""
    async with SessionFactory() as session:
        business = await BusinessRepository(session).get()
        operator = await OperatorRepository(session).get()

    missing = [
        name
        for name, row in (("business_number", business), ("operator", operator))
        if row is None
    ]
    if missing:
        raise RuntimeError(
            f"Seed rows missing: {', '.join(missing)}. Run `make migrate` "
            "then `make seed`."
        )

    return business


async def _replay_webhook_events() -> None:
    """Events stored before a crash/restart (processed_at IS NULL) get applied
    now. Never blocks startup on failure."""
    try:
        await WebhookProcessor().replay_unprocessed()
    except Exception:
        logger.exception("webhook_replay_failed")


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("application_starting")

    _check_dev_static_otp()
    app.state.business = await _load_seeded_rows()

    http = create_http_client()
    app.state.meta = MetaClient(http)

    await _replay_webhook_events()

    try:
        yield
    finally:
        await http.aclose()
        await engine.dispose()

    logger.info("application_stopping")

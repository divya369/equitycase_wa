from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from config.app_config import app_config
from core.database import engine

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


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("application_starting")

    _check_dev_static_otp()

    yield

    await engine.dispose()

    logger.info("application_stopping")

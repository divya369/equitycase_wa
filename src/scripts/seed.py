"""Seed the singleton business_number and operator rows.

Idempotent — run it any number of times:  make seed
"""

import asyncio
import re
import sys

import structlog
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from config.database_config import DatabaseConfig
from config.logging import configure_logging
from config.seed_config import SeedConfig
from modules.business.repository import BusinessRepository
from modules.operator.repository import OperatorRepository

logger = structlog.get_logger("seed")


def digits(value: str) -> str:
    return re.sub(r"\D", "", value)


async def seed(cfg: SeedConfig, database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine) as session:
            await BusinessRepository(session).upsert(
                phone_number_id=cfg.business_phone_number_id,
                waba_id=cfg.business_waba_id,
                display_phone=cfg.business_display_phone,
                verified_name=cfg.business_verified_name,
            )
            await OperatorRepository(session).upsert(
                phone=cfg.owner_phone,
                wa_id=digits(cfg.owner_phone),
                name=cfg.owner_name,
            )
            await session.commit()
    finally:
        await engine.dispose()


def main() -> int:
    configure_logging()

    try:
        cfg = SeedConfig()
        database_url = DatabaseConfig().database_url.get_secret_value()
    except Exception as e:
        logger.error("seed_config_invalid", error=str(e))
        return 1

    if digits(cfg.owner_phone) == digits(cfg.business_display_phone):
        if cfg.otp_channel == "whatsapp":
            # NUMBER LOCK-IN: a Cloud API number can't use the WhatsApp app,
            # so it can never receive its own OTP over WhatsApp.
            logger.error(
                "seed_refused",
                reason="OWNER_PHONE must differ from the business number "
                "when OTP_CHANNEL=whatsapp",
            )
            return 1
        logger.warning(
            "owner_phone_equals_business_number",
            note="allowed for SMS OTP, but a separate number is recommended",
        )

    asyncio.run(seed(cfg, database_url))

    logger.info(
        "seed_complete",
        business_phone_number_id=cfg.business_phone_number_id,
        operator_wa_id=digits(cfg.owner_phone),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

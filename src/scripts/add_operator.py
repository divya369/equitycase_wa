"""Add (or rename) an operator who may log in to the shared inbox.

    python -m scripts.add_operator +919820011223 "Ananya"

Idempotent: run it again for the same number and only the name/phone format
is refreshed. The first operator (id = 1) comes from `make seed`, not here.
"""

import argparse
import asyncio
import sys

import structlog
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from config.database_config import DatabaseConfig
from config.logging import configure_logging
from core.phone import PhoneStr, to_display_phone, to_wa_id
from modules.operator.repository import OperatorRepository

logger = structlog.get_logger("add_operator")

_phone_adapter = TypeAdapter(PhoneStr)


async def add(*, phone: str, name: str, database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine) as session:
            operators = OperatorRepository(session)
            wa_id = to_wa_id(phone)

            operator = await operators.get_by_wa_id(wa_id)
            if operator is None:
                operator = await operators.create(phone=phone, wa_id=wa_id, name=name)
                event = "operator_added"
            else:
                operator.phone = phone
                await operators.update_name(operator, name)
                event = "operator_updated"

            # read before the commit: committing expires the instance
            operator_id = operator.id
            await session.commit()
            logger.info(event, operator_id=operator_id, name=name)
    finally:
        await engine.dispose()


def main() -> int:
    configure_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("phone", help="login number, E.164 (e.g. +919820011223)")
    parser.add_argument("name", help="display name")
    args = parser.parse_args()

    try:
        phone = to_display_phone(_phone_adapter.validate_python(args.phone))
        database_url = DatabaseConfig().database_url.get_secret_value()
    except Exception as e:
        logger.error("add_operator_invalid_input", error=str(e))
        return 1

    asyncio.run(add(phone=phone, name=args.name, database_url=database_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())

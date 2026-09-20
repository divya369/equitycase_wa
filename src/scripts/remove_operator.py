"""Remove an operator: they can no longer log in, and their devices stop
getting pushes (the fcm_tokens rows go with them).

    python -m scripts.remove_operator +919820011223

The seeded operator (id = 1) is refused — change OWNER_PHONE and run
`make seed` instead. Chats and messages are shared, so nothing else is
deleted.
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
from core.phone import PhoneStr, to_wa_id
from core.security import SEEDED_OPERATOR_ID
from modules.operator.repository import OperatorRepository

logger = structlog.get_logger("remove_operator")

_phone_adapter = TypeAdapter(PhoneStr)


async def remove(*, wa_id: str, database_url: str) -> int:
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine) as session:
            operators = OperatorRepository(session)
            operator = await operators.get_by_wa_id(wa_id)
            if operator is None:
                logger.error("operator_not_found")
                return 1
            if operator.id == SEEDED_OPERATOR_ID:
                logger.error(
                    "remove_refused",
                    reason="the seeded operator: change OWNER_PHONE + `make seed`",
                )
                return 1

            operator_id = operator.id
            await operators.delete(operator)
            await session.commit()
            logger.info("operator_removed", operator_id=operator_id)
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    configure_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("phone", help="login number of the operator to remove")
    args = parser.parse_args()

    try:
        wa_id = to_wa_id(_phone_adapter.validate_python(args.phone))
        database_url = DatabaseConfig().database_url.get_secret_value()
    except Exception as e:
        logger.error("remove_operator_invalid_input", error=str(e))
        return 1

    return asyncio.run(remove(wa_id=wa_id, database_url=database_url))


if __name__ == "__main__":
    sys.exit(main())

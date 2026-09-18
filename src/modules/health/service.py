import structlog

from core.database import ping_database
from errors.exceptions import ServiceUnavailableError

logger = structlog.get_logger("health")


class HealthService:
    async def check(self) -> None:
        try:
            await ping_database()
        except Exception as e:
            logger.error("healthcheck_database_failed", error=type(e).__name__)
            raise ServiceUnavailableError("Database unavailable") from e

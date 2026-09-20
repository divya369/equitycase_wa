import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.operator.models import Operator
from modules.operator.repository import FcmTokenRepository, OperatorRepository

logger = structlog.get_logger("operator_service")


class OperatorService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        operators: OperatorRepository,
        fcm_tokens: FcmTokenRepository,
    ):
        self.session = session
        self.operators = operators
        self.fcm_tokens = fcm_tokens

    async def update_name(self, operator: Operator, name: str) -> Operator:
        operator = await self.operators.update_name(operator, name)
        await self.session.commit()
        return operator

    async def register_fcm_token(
        self, *, token: str, platform: str, operator_id: int
    ) -> None:
        await self.fcm_tokens.upsert(
            token=token, platform=platform, operator_id=operator_id
        )
        await self.session.commit()
        logger.info("fcm_token_registered", platform=platform, operator_id=operator_id)

    async def remove_fcm_token(self, token: str) -> None:
        await self.fcm_tokens.delete(token)
        await self.session.commit()
        logger.info("fcm_token_removed")

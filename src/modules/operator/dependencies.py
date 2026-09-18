from typing import Annotated

from fastapi import Depends

from core.database import SessionDep
from modules.operator.repository import FcmTokenRepository, OperatorRepository
from modules.operator.service import OperatorService


def get_operator_service(session: SessionDep) -> OperatorService:
    return OperatorService(
        session=session,
        operators=OperatorRepository(session),
        fcm_tokens=FcmTokenRepository(session),
    )


OperatorServiceDep = Annotated[OperatorService, Depends(get_operator_service)]

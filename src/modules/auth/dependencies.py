from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.database import SessionDep
from core.security import InvalidTokenError, decode_access_token
from errors.exceptions import UnauthorizedError
from integrations.sms.sender import get_otp_sender
from modules.auth.repository import OtpRepository
from modules.auth.service import AuthService
from modules.operator.models import Operator
from modules.operator.repository import OperatorRepository

_bearer = HTTPBearer(auto_error=False)


def get_auth_service(session: SessionDep) -> AuthService:
    return AuthService(
        session=session,
        otps=OtpRepository(session),
        operators=OperatorRepository(session),
        sender=get_otp_sender(),
    )


async def get_current_operator(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Operator:
    if credentials is None:
        raise UnauthorizedError("Missing bearer token")

    try:
        decode_access_token(credentials.credentials)
    except InvalidTokenError as e:
        raise UnauthorizedError("Invalid or expired token") from e

    operator = await OperatorRepository(session).get()
    if operator is None:
        raise UnauthorizedError()
    return operator


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
CurrentOperator = Annotated[Operator, Depends(get_current_operator)]

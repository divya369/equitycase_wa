import re
from datetime import timedelta

import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from config.app_config import app_config
from core.security import (
    constant_time_equals,
    create_access_token,
    generate_otp,
    hash_otp,
    verify_otp_hash,
)
from core.time import utcnow
from errors.exceptions import InvalidOtpError, UpstreamError
from integrations.sms.sender import OtpSender
from modules.auth.repository import OtpRepository
from modules.operator.models import Operator
from modules.operator.repository import OperatorRepository

logger = structlog.get_logger("auth_service")

OTP_TTL = timedelta(minutes=5)
OTP_MAX_ATTEMPTS = 5


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


class AuthService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        otps: OtpRepository,
        operators: OperatorRepository,
        sender: OtpSender,
    ):
        self.session = session
        self.otps = otps
        self.operators = operators
        self.sender = sender

    async def _operator_for_phone(self, phone: str) -> Operator | None:
        operator = await self.operators.get()
        if operator is None or _digits(phone) != operator.wa_id:
            return None
        return operator

    async def request_otp(self, phone: str) -> None:
        """Always succeeds for the caller — never reveals which phone is valid."""
        operator = await self._operator_for_phone(phone)
        if operator is None:
            logger.info("otp_request_ignored_unknown_phone")
            return

        if app_config.dev_static_otp is not None:
            logger.warning("otp_request_dev_static_otp_in_use")
            return

        code = generate_otp()
        await self.otps.invalidate_active()
        await self.otps.create(
            code_hash=await hash_otp(code), expires_at=utcnow() + OTP_TTL
        )
        await self.session.commit()

        try:
            await self.sender.send_otp(phone=operator.phone, code=code)
        except Exception as e:
            logger.error("otp_delivery_failed", error=type(e).__name__)
            raise UpstreamError("Could not deliver the code. Try again.") from e

        logger.info("otp_issued")

    async def verify_otp(self, *, phone: str, code: str) -> tuple[str, Operator]:
        operator = await self._operator_for_phone(phone)
        if operator is None:
            raise InvalidOtpError()

        if app_config.dev_static_otp is not None:
            if not constant_time_equals(
                code, app_config.dev_static_otp.get_secret_value()
            ):
                raise InvalidOtpError()
            logger.warning("otp_verified_with_dev_static_otp")
            return create_access_token(), operator

        otp = await self.otps.get_newest_active_for_update()
        if otp is None or otp.attempts >= OTP_MAX_ATTEMPTS:
            await self.session.rollback()
            raise InvalidOtpError()

        # Count the attempt BEFORE checking, and persist it even on failure
        otp.attempts += 1
        valid = await verify_otp_hash(otp.code_hash, code)
        if valid:
            otp.consumed_at = utcnow()
        self.session.add(otp)
        await self.session.commit()

        if not valid:
            logger.info("otp_verify_failed", attempts=otp.attempts)
            raise InvalidOtpError()

        logger.info("otp_verified")
        return create_access_token(), operator

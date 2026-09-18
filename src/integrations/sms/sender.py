from typing import Protocol

import structlog

logger = structlog.get_logger("otp_sender")


class OtpSender(Protocol):
    async def send_otp(self, *, phone: str, code: str) -> None:
        """Deliver `code` to `phone` (E.164 with +). Raise on failure."""
        ...


class NullOtpSender:
    """Used until the SMSForYou sender exists (P9). Delivers nothing.

    Logs WITHOUT the code — OTP codes are never logged.
    """

    async def send_otp(self, *, phone: str, code: str) -> None:
        logger.error(
            "otp_sender_not_configured",
            hint="set DEV_STATIC_OTP for local login, or configure SMSForYou",
        )


def get_otp_sender() -> OtpSender:
    # P9: return SmsForYouSender(...) when its settings are present
    return NullOtpSender()

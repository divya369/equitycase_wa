from typing import Protocol

import httpx
import structlog

from config.app_config import app_config
from core.phone import to_wa_id

logger = structlog.get_logger("otp_sender")

# DLT-approved template: the text must match it exactly or the SMS is dropped
OTP_MESSAGE = (
    "{code} is your otp to verify your mobile number. Please do not share it "
    "with anyone for security reason. Anand Money Changers Mo: 7400874009"
)


class OtpSender(Protocol):
    async def send_otp(self, *, phone: str, code: str) -> None:
        """Deliver `code` to `phone` (E.164 with +). Raise on failure."""
        ...


class SmsDeliveryError(Exception):
    pass


class SmsForYouSender:
    """GET <SMS_API_URL>?apikey&senderid&number&message&format=json.

    The URL carries the API key and the code, so it is never logged (httpx's
    own request logging is silenced in config/logging.py). Sent once, never
    retried — a retry could deliver two codes.
    """

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        sender_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.sender_id = sender_id
        self.transport = transport

    async def send_otp(self, *, phone: str, code: str) -> None:
        params = {
            "apikey": self.api_key,
            "senderid": self.sender_id,
            # country code + number, digits only (e.g. 91XXXXXXXXXX)
            "number": to_wa_id(phone),
            "message": OTP_MESSAGE.format(code=code),
            "format": "json",
        }
        async with httpx.AsyncClient(
            timeout=app_config.sms_http_timeout_seconds, transport=self.transport
        ) as http:
            try:
                resp = await http.get(self.api_url, params=params)
            except httpx.TransportError as e:
                logger.warning("sms_otp_transport_error", error=type(e).__name__)
                raise SmsDeliveryError("SMS gateway unreachable") from e

        if resp.is_error:
            logger.warning("sms_otp_rejected", http_status=resp.status_code)
            raise SmsDeliveryError(f"SMS gateway returned {resp.status_code}")
        logger.info("sms_otp_sent", http_status=resp.status_code)


class NullOtpSender:
    """Used when the SMS settings are missing. Delivers nothing.

    Logs WITHOUT the code — OTP codes are never logged.
    """

    async def send_otp(self, *, phone: str, code: str) -> None:
        logger.error(
            "otp_sender_not_configured",
            hint="set SMS_API_URL, SMS_API_KEY and SENDER_ID (or DEV_STATIC_OTP)",
        )


def get_otp_sender() -> OtpSender:
    if app_config.sms_api_url and app_config.sms_api_key and app_config.sender_id:
        return SmsForYouSender(
            api_url=app_config.sms_api_url,
            api_key=app_config.sms_api_key.get_secret_value(),
            sender_id=app_config.sender_id,
        )
    return NullOtpSender()

"""Firebase Cloud Messaging: data-only pushes to the operator's phones.

firebase-admin is synchronous — every call goes through asyncio.to_thread so
it never blocks the event loop. The client is created once in lifespan
(`init_fcm`); background code reaches it through `get_fcm_client()`.
"""

import asyncio
import warnings
from typing import Protocol

import firebase_admin
import structlog
from firebase_admin import credentials, exceptions, messaging

from config.app_config import app_config

logger = structlog.get_logger("fcm_client")

FIREBASE_APP_NAME = "equitycase"
# FCM's multicast limit
MAX_TOKENS_PER_CALL = 500


class PushClient(Protocol):
    async def send_data(self, tokens: list[str], data: dict[str, str]) -> list[str]:
        """Send to every token. Returns the tokens FCM says are dead."""
        ...


def _is_dead_token(error: Exception | None) -> bool:
    """UNREGISTERED (app uninstalled / token rotated), another project's
    token, or a malformed token. Anything else (quota, outage) keeps it."""
    if isinstance(
        error, (messaging.UnregisteredError, messaging.SenderIdMismatchError)
    ):
        return True
    return isinstance(error, exceptions.InvalidArgumentError) and (
        "registration token" in str(error).lower()
    )


class FcmClient:
    def __init__(self, app: firebase_admin.App):
        self.app = app

    async def send_data(self, tokens: list[str], data: dict[str, str]) -> list[str]:
        dead: list[str] = []
        for start in range(0, len(tokens), MAX_TOKENS_PER_CALL):
            batch = tokens[start : start + MAX_TOKENS_PER_CALL]
            response = await asyncio.to_thread(
                messaging.send_each_for_multicast,
                self._message(batch, data),
                app=self.app,
            )
            for token, result in zip(batch, response.responses, strict=True):
                if result.success:
                    continue
                if _is_dead_token(result.exception):
                    dead.append(token)
                else:
                    logger.warning(
                        "fcm_send_failed", error=type(result.exception).__name__
                    )
            logger.info(
                "fcm_sent", sent=response.success_count, failed=response.failure_count
            )
        return dead

    @staticmethod
    def _message(tokens: list[str], data: dict[str, str]) -> messaging.MulticastMessage:
        # DATA-ONLY: the app decides how to show it. All values are strings.
        with warnings.catch_warnings():
            # firebase-admin 7.x flags `tokens` in favour of `fids`, but fids
            # are Installation IDs — the app registers FCM registration
            # tokens (getToken()), which still belong in `tokens`.
            warnings.simplefilter("ignore", DeprecationWarning)
            return messaging.MulticastMessage(
                tokens=tokens,
                data=data,
                android=messaging.AndroidConfig(priority="high"),
                apns=messaging.APNSConfig(
                    headers={"apns-push-type": "background", "apns-priority": "5"},
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(content_available=True)
                    ),
                ),
            )


_client: PushClient | None = None


def init_fcm() -> None:
    """Lifespan: build the client from FIREBASE_CREDENTIALS (a service-account
    JSON path). Unset = pushes are off; a bad file fails startup."""
    global _client
    path = app_config.firebase_credentials
    if not path:
        logger.warning("fcm_disabled", hint="set FIREBASE_CREDENTIALS to enable push")
        _client = None
        return
    try:
        app = firebase_admin.get_app(FIREBASE_APP_NAME)
    except ValueError:
        try:
            app = firebase_admin.initialize_app(
                credentials.Certificate(path), name=FIREBASE_APP_NAME
            )
        except (OSError, ValueError) as e:
            raise RuntimeError(
                "FIREBASE_CREDENTIALS is not a readable service-account JSON"
            ) from e
    _client = FcmClient(app)
    logger.info("fcm_enabled")


def get_fcm_client() -> PushClient | None:
    return _client


def set_fcm_client(client: PushClient | None) -> None:
    """Tests swap in a fake."""
    global _client
    _client = client

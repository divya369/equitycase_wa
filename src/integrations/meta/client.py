"""WhatsApp Cloud API client.

ONE shared httpx.AsyncClient (created in lifespan). Retries 429/5xx and
connection failures with exponential backoff; never retries other 4xx. The
access token is sent as a header and never logged.
"""

import asyncio
from typing import Any

import httpx
import structlog

from config.app_config import app_config
from integrations.meta.errors import MetaApiError

logger = structlog.get_logger("meta_client")

MAX_ATTEMPTS = 3


def create_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=app_config.meta_http_timeout_seconds)


class MetaClient:
    def __init__(self, http: httpx.AsyncClient, *, backoff_seconds: float = 0.5):
        self.http = http
        self.backoff_seconds = backoff_seconds
        self.base_url = (
            f"{app_config.meta_graph_base_url.rstrip('/')}/"
            f"{app_config.meta_api_version}"
        )

    @property
    def _headers(self) -> dict[str, str]:
        token = app_config.meta_access_token.get_secret_value()
        return {"Authorization": f"Bearer {token}"}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{path}"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last = attempt == MAX_ATTEMPTS
            try:
                resp = await self.http.post(url, json=payload, headers=self._headers)
            except httpx.ConnectError as e:
                # Never reached Meta, so a retry cannot double-send. A read
                # timeout might have been delivered — that one is NOT retried.
                logger.warning("meta_connect_failed", attempt=attempt)
                if last:
                    raise MetaApiError(
                        code=None, title="Could not reach WhatsApp"
                    ) from e
            except httpx.TransportError as e:
                logger.warning("meta_transport_error", error=type(e).__name__)
                raise MetaApiError(code=None, title="WhatsApp did not respond") from e
            else:
                retryable = resp.status_code == 429 or resp.status_code >= 500
                if not resp.is_error:
                    return resp.json()
                if not retryable or last:
                    error = MetaApiError.from_response(resp)
                    logger.warning(
                        "meta_api_error",
                        http_status=resp.status_code,
                        code=error.code,
                        attempt=attempt,
                    )
                    raise error
                logger.warning(
                    "meta_api_retry", http_status=resp.status_code, attempt=attempt
                )

            await asyncio.sleep(self.backoff_seconds * 2 ** (attempt - 1))

        raise AssertionError("unreachable")

    async def send_text(
        self,
        *,
        phone_number_id: str,
        to: str,
        body: str,
        reply_to_wamid: str | None = None,
    ) -> str:
        """Returns the wamid Meta assigned to the message."""
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": True, "body": body},
        }
        if reply_to_wamid:
            payload["context"] = {"message_id": reply_to_wamid}

        data = await self._post(f"{phone_number_id}/messages", payload)
        try:
            return data["messages"][0]["id"]
        except (KeyError, IndexError, TypeError) as e:
            raise MetaApiError(code=None, title="Unexpected WhatsApp response") from e

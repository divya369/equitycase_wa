import json
from typing import Any

import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from config.app_config import app_config
from core.security import constant_time_equals
from errors.exceptions import ForbiddenError
from modules.business.repository import BusinessRepository
from modules.webhook.repository import WebhookEventRepository
from modules.webhook.signature import is_valid_signature

logger = structlog.get_logger("webhook_service")

Event = tuple[str, dict[str, Any]]


def extract_events(payload: dict[str, Any], *, phone_number_id: str) -> list[Event]:
    """Split a Meta webhook body into one stored event per message / status.

    event_key: "msg:<wamid>" | "status:<wamid>:<status>". Changes addressed
    to another phone number of the same app are ignored.
    """
    events: list[Event] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            if change.get("field") != "messages":
                logger.info("webhook_field_ignored", field=change.get("field"))
                continue

            metadata = value.get("metadata") or {}
            if metadata.get("phone_number_id") != phone_number_id:
                logger.warning("webhook_foreign_phone_number_ignored")
                continue

            for error in value.get("errors") or []:
                logger.warning(
                    "webhook_error_reported",
                    code=error.get("code"),
                    title=error.get("title"),
                )

            for message in value.get("messages") or []:
                if message.get("id"):
                    events.append(
                        (
                            f"msg:{message['id']}",
                            {
                                "kind": "message",
                                "message": message,
                                "contacts": value.get("contacts") or [],
                            },
                        )
                    )

            for status in value.get("statuses") or []:
                if status.get("id") and status.get("status"):
                    events.append(
                        (
                            f"status:{status['id']}:{status['status']}",
                            {"kind": "status", "status": status},
                        )
                    )
    return events


class WebhookService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        events: WebhookEventRepository,
        business: BusinessRepository,
    ):
        self.session = session
        self.events = events
        self.business = business

    @staticmethod
    def verify_subscription(
        *, mode: str | None, verify_token: str | None, challenge: str | None
    ) -> str:
        """GET handshake: echo hub.challenge when the verify token matches."""
        expected = app_config.meta_verify_token.get_secret_value()
        if (
            mode != "subscribe"
            or not verify_token
            or challenge is None
            or not constant_time_equals(verify_token, expected)
        ):
            logger.warning("webhook_verification_failed")
            raise ForbiddenError("Webhook verification failed")
        logger.info("webhook_verified")
        return challenge

    async def receive(self, body: bytes, signature: str | None) -> list[str]:
        """Verify, then persist BEFORE the 200 goes back. Returns the keys of
        NEW events, to be processed in the background."""
        if not is_valid_signature(body, signature):
            # sizes only (never the body): a re-formatted test body shows up
            # as an unexpected body_bytes
            logger.warning(
                "webhook_signature_invalid",
                body_bytes=len(body),
                has_signature=bool(signature),
            )
            raise ForbiddenError("Invalid signature")

        try:
            payload = json.loads(body)
        except ValueError:
            logger.warning("webhook_body_not_json")
            return []
        if not isinstance(payload, dict):
            logger.warning("webhook_body_not_object")
            return []

        business = await self.business.get()
        events = extract_events(payload, phone_number_id=business.phone_number_id)
        keys = await self.events.insert_new(events)
        await self.session.commit()

        logger.info("webhook_received", events=len(events), new=len(keys))
        return keys

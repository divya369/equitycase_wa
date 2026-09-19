"""Applies stored webhook events. Runs after the 200 (BackgroundTask), on
startup (replay) and right after a send gets its wamid.

Every event runs in its OWN session + transaction; a failing event stays
unprocessed (processed_at IS NULL) and is retried on the next replay.
"""

from datetime import timedelta
from typing import Any

import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from core.database import SessionFactory
from core.time import utcnow
from modules.messages.models import MessageStatus
from modules.messages.repository import MessageRepository
from modules.webhook.models import WebhookEvent
from modules.webhook.repository import WebhookEventRepository

logger = structlog.get_logger("webhook_processor")

STATUS_BY_LABEL = {
    "sent": MessageStatus.SENT,
    "delivered": MessageStatus.DELIVERED,
    "read": MessageStatus.READ,
    "failed": MessageStatus.FAILED,
}

# A status for a wamid we don't know yet may simply have beaten our own
# "sent" commit. After this long it's a message we never sent (e.g. from
# another tool on the same number) — stop retrying it.
UNMATCHED_STATUS_TTL = timedelta(hours=1)


class WebhookProcessor:
    async def process(self, keys: list[str]) -> None:
        for key in keys:
            await self._process_one(key)

    async def replay_unprocessed(self) -> int:
        async with SessionFactory() as session:
            keys = await WebhookEventRepository(session).list_unprocessed_keys()
        await self.process(keys)
        if keys:
            logger.info("webhook_replayed", events=len(keys))
        return len(keys)

    async def process_pending_statuses(self, wamid: str) -> None:
        """Statuses that arrived before we stored this wamid."""
        async with SessionFactory() as session:
            keys = await WebhookEventRepository(session).list_unprocessed_keys(
                prefix=f"status:{wamid}:"
            )
        await self.process(keys)

    async def _process_one(self, key: str) -> None:
        async with SessionFactory() as session:
            events = WebhookEventRepository(session)
            event = await events.get(key)
            if event is None or event.processed_at is not None:
                return
            try:
                done = await self._apply(session, event)
                if done:
                    await events.mark_processed(key)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("webhook_event_failed", event_key=key)

    async def _apply(self, session: AsyncSession, event: WebhookEvent) -> bool:
        """True when the event is finished with (applied or deliberately
        ignored); False to leave it for a later retry."""
        kind = event.payload.get("kind")
        if kind == "status":
            return await self._apply_status(session, event)
        if kind == "message":
            # inbound messages are handled in P6; keep them for replay
            return False
        logger.warning("webhook_event_kind_unknown", event_key=event.event_key)
        return True

    async def _apply_status(self, session: AsyncSession, event: WebhookEvent) -> bool:
        status: dict[str, Any] = event.payload["status"]
        new = STATUS_BY_LABEL.get(status.get("status"))
        if new is None:
            logger.info("webhook_status_ignored", status=status.get("status"))
            return True

        messages = MessageRepository(session)
        message = await messages.get_by_wamid(status["id"])
        if message is None:
            if utcnow() - event.received_at > UNMATCHED_STATUS_TTL:
                logger.warning("webhook_status_unmatched_dropped", status=new.label)
                return True
            logger.info("webhook_status_unmatched_waiting", status=new.label)
            return False

        if new is MessageStatus.FAILED:
            error = (status.get("errors") or [{}])[0]
            changed = await messages.mark_failed(
                message.id,
                code=error.get("code"),
                title=error.get("title") or error.get("message") or "Failed",
            )
        else:
            changed = await messages.advance_status(message.id, new)

        logger.info(
            "message_status_updated" if changed else "message_status_stale",
            message_id=str(message.id),
            status=new.label,
        )
        # the message.status WS broadcast is wired in P7
        return True

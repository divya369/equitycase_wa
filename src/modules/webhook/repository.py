from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from core.time import utcnow
from modules.webhook.models import WebhookEvent


class WebhookEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, event_key: str) -> WebhookEvent | None:
        return await self.session.get(WebhookEvent, event_key)

    async def insert_new(self, events: list[tuple[str, dict[str, Any]]]) -> list[str]:
        """ON CONFLICT DO NOTHING. Returns only the keys that were new —
        Meta redelivers the same event, and a repeat must not be reprocessed."""
        if not events:
            return []
        stmt = (
            insert(WebhookEvent)
            .values(
                [
                    {"event_key": key, "payload": payload, "received_at": utcnow()}
                    for key, payload in events
                ]
            )
            .on_conflict_do_nothing(index_elements=["event_key"])
            .returning(WebhookEvent.event_key)
        )
        inserted = set((await self.session.exec(stmt)).scalars().all())
        # keep Meta's order (statuses of one message arrive sent -> read)
        return [key for key, _ in events if key in inserted]

    async def list_unprocessed_keys(self, *, prefix: str = "") -> list[str]:
        stmt = (
            select(WebhookEvent.event_key)
            .where(WebhookEvent.processed_at.is_(None))
            .order_by(WebhookEvent.received_at, WebhookEvent.event_key)
        )
        if prefix:
            stmt = stmt.where(WebhookEvent.event_key.startswith(prefix))
        return list((await self.session.exec(stmt)).all())

    async def mark_processed(self, event_key: str) -> None:
        await self.session.exec(
            update(WebhookEvent)
            .where(
                WebhookEvent.event_key == event_key,
                WebhookEvent.processed_at.is_(None),
            )
            .values(processed_at=utcnow())
        )

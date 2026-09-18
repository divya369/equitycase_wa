from datetime import datetime
from typing import Any

from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from core.columns import timestamp_column
from core.time import utcnow


class WebhookEvent(SQLModel, table=True):
    """Durability + idempotency for Meta webhooks.

    Stored BEFORE returning 200; rows with processed_at IS NULL are replayed
    on startup.
    """

    __tablename__ = "webhook_events"

    # "msg:<wamid>" or "status:<wamid>:<status>"
    event_key: str = Field(sa_column=Column(Text, primary_key=True))
    payload: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    received_at: datetime = Field(default_factory=utcnow, sa_column=timestamp_column())
    processed_at: datetime | None = Field(
        default=None,
        sa_column=timestamp_column(nullable=True, now_default=False),
    )

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlmodel import Field, SQLModel

from core.columns import timestamp_column, uuid_pk_column
from core.time import utcnow


class Chat(SQLModel, table=True):
    __tablename__ = "chats"
    __table_args__ = (
        UniqueConstraint("contact_wa_id", name="uq_chats_contact_wa_id"),
        # Postgres scans a btree backwards, so this serves
        # ORDER BY is_pinned DESC, updated_at DESC
        Index("ix_chats_pinned_updated", "is_pinned", "updated_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_column=uuid_pk_column())
    contact_wa_id: str = Field(
        sa_column=Column(
            Text,
            ForeignKey("contacts.wa_id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    # chats <-> messages reference each other; use_alter adds this FK after
    # both tables exist
    last_message_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey(
                "messages.id",
                ondelete="SET NULL",
                use_alter=True,
                name="fk_chats_last_message_id_messages",
            ),
            nullable=True,
        ),
    )
    unread_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    is_pinned: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    is_muted: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    # Drives the 24h customer-service window
    last_inbound_at: datetime | None = Field(
        default=None,
        sa_column=timestamp_column(nullable=True, now_default=False),
    )
    created_at: datetime = Field(default_factory=utcnow, sa_column=timestamp_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=timestamp_column())

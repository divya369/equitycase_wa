import uuid
from datetime import datetime
from enum import IntEnum, StrEnum

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlmodel import Field, SQLModel

from core.columns import text_column, timestamp_column, uuid_pk_column
from core.time import utcnow


class MessageStatus(IntEnum):
    """ORDERED. Never move backwards (UPDATE ... WHERE status < :new).

    The only exception is POST /v1/messages/{id}/retry: FAILED -> PENDING.
    """

    PENDING = 0
    SENT = 1
    DELIVERED = 2
    READ = 3
    FAILED = 4

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def from_label(cls, label: str) -> MessageStatus:
        return cls[label.upper()]


class MessageDirection(StrEnum):
    IN = "in"
    OUT = "out"


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("direction IN ('in', 'out')", name="ck_messages_direction"),
        CheckConstraint("status BETWEEN 0 AND 4", name="ck_messages_status"),
        UniqueConstraint("wamid", name="uq_messages_wamid"),
        # Postgres scans a btree backwards, so this serves
        # WHERE chat_id = ? ORDER BY created_at DESC
        Index("ix_messages_chat_created", "chat_id", "created_at"),
        # POST /messages idempotency key
        Index(
            "uq_messages_chat_client_msg_id",
            "chat_id",
            "client_msg_id",
            unique=True,
            postgresql_where=text("client_msg_id IS NOT NULL"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_column=uuid_pk_column())
    chat_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("chats.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    # Meta id; null until the send is ACKed
    wamid: str | None = Field(default=None, sa_column=text_column(nullable=True))
    # The client's optimistic uuid
    client_msg_id: str | None = Field(
        default=None, sa_column=text_column(nullable=True)
    )
    # Customer wa_id, or the business number
    sender_wa_id: str = Field(sa_column=text_column())
    direction: MessageDirection = Field(sa_column=Column(Text, nullable=False))
    type: str = Field(default="text", sa_column=text_column(default="text"))
    body: str = Field(default="", sa_column=text_column(default=""))
    media_id: str | None = Field(default=None, sa_column=text_column(nullable=True))
    media_url: str | None = Field(default=None, sa_column=text_column(nullable=True))
    media_mime: str | None = Field(default=None, sa_column=text_column(nullable=True))
    reply_to_wamid: str | None = Field(
        default=None, sa_column=text_column(nullable=True)
    )
    status: int = Field(
        default=MessageStatus.PENDING,
        sa_column=Column(SmallInteger, nullable=False, server_default=text("0")),
    )
    error_code: int | None = Field(default=None, sa_column=Column(Integer))
    error_title: str | None = Field(default=None, sa_column=text_column(nullable=True))
    created_at: datetime = Field(default_factory=utcnow, sa_column=timestamp_column())

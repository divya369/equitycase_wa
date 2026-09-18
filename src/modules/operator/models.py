from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    SmallInteger,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel

from core.columns import text_column, timestamp_column
from core.time import utcnow


class Operator(SQLModel, table=True):
    """The ONE person using the Flutter app. Seeded; there is no signup."""

    __tablename__ = "operator"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_operator_singleton"),
        UniqueConstraint("phone", name="uq_operator_phone"),
        UniqueConstraint("wa_id", name="uq_operator_wa_id"),
    )

    id: int = Field(
        default=1,
        sa_column=Column(
            SmallInteger,
            primary_key=True,
            autoincrement=False,
            server_default=text("1"),
        ),
    )
    # E.164 with +, e.g. +919820011223
    phone: str = Field(sa_column=text_column())
    # digits only
    wa_id: str = Field(sa_column=text_column())
    name: str = Field(default="You", sa_column=text_column(default="You"))
    about: str = Field(default="", sa_column=text_column(default=""))
    avatar_url: str | None = Field(default=None, sa_column=text_column(nullable=True))
    created_at: datetime = Field(default_factory=utcnow, sa_column=timestamp_column())


class FcmToken(SQLModel, table=True):
    """One row per operator device."""

    __tablename__ = "fcm_tokens"
    __table_args__ = (
        UniqueConstraint("token", name="uq_fcm_tokens_token"),
        CheckConstraint(
            "platform IN ('android', 'ios')", name="ck_fcm_tokens_platform"
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    token: str = Field(sa_column=text_column())
    platform: str = Field(sa_column=text_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=timestamp_column())

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    SmallInteger,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from core.columns import text_column, timestamp_column
from core.time import utcnow


class Operator(SQLModel, table=True):
    """A person using the Flutter app. They share ONE inbox: every operator
    sees every chat. id = 1 is the seeded one (`make seed`); the others are
    added with `python -m scripts.add_operator`. There is no signup.
    """

    __tablename__ = "operator"
    __table_args__ = (
        UniqueConstraint("phone", name="uq_operator_phone"),
        UniqueConstraint("wa_id", name="uq_operator_wa_id"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(SmallInteger, primary_key=True, autoincrement=True),
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
    """One row per device. `operator_id` decides who gets a push: a device
    whose operator is already on a WebSocket is skipped."""

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
    operator_id: int = Field(
        sa_column=Column(
            SmallInteger,
            ForeignKey(
                "operator.id", ondelete="CASCADE", name="fk_fcm_tokens_operator"
            ),
            nullable=False,
            index=True,
        )
    )
    token: str = Field(sa_column=text_column())
    platform: str = Field(sa_column=text_column())
    updated_at: datetime = Field(default_factory=utcnow, sa_column=timestamp_column())

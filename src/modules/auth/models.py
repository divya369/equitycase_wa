from datetime import datetime

from sqlalchemy import BigInteger, Column, Index, Integer, text
from sqlmodel import Field, SQLModel

from core.columns import text_column, timestamp_column
from core.time import utcnow


class OtpCode(SQLModel, table=True):
    __tablename__ = "otp_codes"
    # Postgres scans a btree backwards, so a plain index serves ORDER BY ... DESC
    __table_args__ = (Index("ix_otp_codes_created_at", "created_at"),)

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    # argon2 hash — NEVER the plaintext code
    code_hash: str = Field(sa_column=text_column())
    expires_at: datetime = Field(sa_column=timestamp_column(now_default=False))
    attempts: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    consumed_at: datetime | None = Field(
        default=None,
        sa_column=timestamp_column(nullable=True, now_default=False),
    )
    created_at: datetime = Field(default_factory=utcnow, sa_column=timestamp_column())

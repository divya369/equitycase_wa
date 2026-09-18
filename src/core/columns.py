"""Column factories shared by table models.

Each call returns a NEW Column — SQLAlchemy columns cannot be shared between
tables. Python-side defaults are set on the Field so values are known right
after INSERT (no refresh needed); server defaults keep raw SQL inserts valid.
"""

from sqlalchemy import Column, DateTime, Text, func, text
from sqlalchemy.dialects.postgresql import UUID


def uuid_pk_column() -> Column:
    return Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def timestamp_column(*, nullable: bool = False, now_default: bool = True) -> Column:
    return Column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=func.now() if now_default else None,
    )


def text_column(*, nullable: bool = False, default: str | None = None) -> Column:
    return Column(
        Text,
        nullable=nullable,
        server_default=text(f"'{default}'") if default is not None else None,
    )

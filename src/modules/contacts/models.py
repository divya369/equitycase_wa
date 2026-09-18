from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from core.columns import text_column, timestamp_column
from core.time import utcnow


class Contact(SQLModel, table=True):
    """A customer who talks to the business number. Keyed by wa_id (digits only)."""

    __tablename__ = "contacts"

    wa_id: str = Field(sa_column=Column(Text, primary_key=True))
    name: str = Field(sa_column=text_column())
    # display form, e.g. +91 98200 11223
    phone: str = Field(sa_column=text_column())
    about: str = Field(default="", sa_column=text_column(default=""))
    avatar_url: str | None = Field(default=None, sa_column=text_column(nullable=True))
    created_at: datetime = Field(default_factory=utcnow, sa_column=timestamp_column())

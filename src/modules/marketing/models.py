from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from core.columns import text_column, timestamp_column
from core.time import utcnow


class MarketingOptOut(SQLModel, table=True):
    """A customer who asked to stop receiving marketing messages.

    Written when the STOP button (or a "stop" text) arrives on the webhook,
    and read by the blast CLI before every send. Opting back in is manual and
    deliberate: nothing here is removed automatically.
    """

    __tablename__ = "marketing_opt_outs"

    # digits only, no '+': the wa_id is the identity everywhere
    wa_id: str = Field(sa_column=Column(Text, primary_key=True))
    # "stop_button" | "stop_text" | "manual"
    source: str = Field(default="manual", sa_column=text_column(default="manual"))
    created_at: datetime = Field(default_factory=utcnow, sa_column=timestamp_column())

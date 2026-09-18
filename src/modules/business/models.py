from sqlalchemy import CheckConstraint, Column, SmallInteger, text
from sqlmodel import Field, SQLModel

from core.columns import text_column
from core.phone import to_wa_id


class BusinessNumber(SQLModel, table=True):
    """The ONE WhatsApp Business sender number. Seeded, never created by the API."""

    __tablename__ = "business_number"
    __table_args__ = (CheckConstraint("id = 1", name="ck_business_number_singleton"),)

    id: int = Field(
        default=1,
        sa_column=Column(
            SmallInteger,
            primary_key=True,
            autoincrement=False,
            server_default=text("1"),
        ),
    )
    phone_number_id: str = Field(sa_column=text_column())
    # Only needed for template management (P11)
    waba_id: str | None = Field(default=None, sa_column=text_column(nullable=True))
    display_phone: str = Field(sa_column=text_column())
    verified_name: str = Field(default="", sa_column=text_column(default=""))

    @property
    def wa_id(self) -> str:
        """Digits-only form, used as sender_wa_id on outbound messages."""
        return to_wa_id(self.display_phone)

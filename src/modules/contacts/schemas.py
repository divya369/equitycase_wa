from datetime import datetime

from pydantic import BaseModel

from core.phone import PhoneStr
from modules.contacts.models import Contact
from modules.operator.models import Operator
from modules.operator.schemas import NameStr


class CreateContactIn(BaseModel):
    name: NameStr
    phone: PhoneStr


class UserOut(BaseModel):
    """The Dart `user` model — used for the operator AND for contacts.

    The Cloud API exposes no presence: is_online is always False and
    last_seen always None. Never fabricate them.
    """

    wa_id: str
    name: str
    phone: str
    avatar_url: str | None
    about: str
    is_online: bool = False
    last_seen: datetime | None = None

    @classmethod
    def from_operator(cls, operator: Operator) -> UserOut:
        return cls(
            wa_id=operator.wa_id,
            name=operator.name,
            phone=operator.phone,
            avatar_url=operator.avatar_url,
            about=operator.about,
        )

    @classmethod
    def from_contact(cls, contact: Contact) -> UserOut:
        return cls(
            wa_id=contact.wa_id,
            name=contact.name,
            phone=contact.phone,
            avatar_url=contact.avatar_url,
            about=contact.about,
        )

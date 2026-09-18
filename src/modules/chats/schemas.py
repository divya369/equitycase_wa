import uuid

from pydantic import BaseModel

from core.phone import PhoneStr
from modules.chats.models import Chat
from modules.contacts.models import Contact
from modules.contacts.schemas import UserOut
from modules.messages.models import Message
from modules.messages.schemas import MessageOut


class OpenChatIn(BaseModel):
    # the contact's wa_id; '+' and spacing are tolerated
    wa_id: PhoneStr


class ChatOut(BaseModel):
    """The Dart `chat` model. Build it ONLY via from_models()."""

    id: uuid.UUID
    contact: UserOut
    last_message: MessageOut | None
    unread_count: int
    is_pinned: bool
    is_muted: bool

    @classmethod
    def from_models(
        cls, chat: Chat, contact: Contact, last_message: Message | None
    ) -> ChatOut:
        return cls(
            id=chat.id,
            contact=UserOut.from_contact(contact),
            last_message=(
                MessageOut.from_model(last_message) if last_message else None
            ),
            unread_count=chat.unread_count,
            is_pinned=chat.is_pinned,
            is_muted=chat.is_muted,
        )

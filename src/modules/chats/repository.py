import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from core.time import utcnow
from modules.chats.models import Chat
from modules.contacts.models import Contact
from modules.messages.models import Message

ChatRow = tuple[Chat, Contact, Message | None]


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _rows(self):
        """Chat + its contact + its last message, in one query."""
        return (
            select(Chat, Contact, Message)
            .join(Contact, Contact.wa_id == Chat.contact_wa_id)
            .outerjoin(Message, Message.id == Chat.last_message_id)
        )

    async def get(self, chat_id: uuid.UUID) -> Chat | None:
        return await self.session.get(Chat, chat_id)

    async def get_by_contact_for_update(self, contact_wa_id: str) -> Chat | None:
        """Row-locked until commit: serialises concurrent inbound processing
        for the same chat (unread_count, last_message_id)."""
        stmt = (
            select(Chat)
            .where(Chat.contact_wa_id == contact_wa_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.exec(stmt)).first()

    async def save(self, chat: Chat) -> Chat:
        self.session.add(chat)
        await self.session.flush()
        return chat

    async def get_row(self, chat_id: uuid.UUID) -> ChatRow | None:
        stmt = self._rows().where(Chat.id == chat_id)
        row = (await self.session.exec(stmt)).first()
        return tuple(row) if row else None

    async def get_row_by_contact(self, contact_wa_id: str) -> ChatRow | None:
        stmt = self._rows().where(Chat.contact_wa_id == contact_wa_id)
        row = (await self.session.exec(stmt)).first()
        return tuple(row) if row else None

    async def list_rows(self) -> list[ChatRow]:
        stmt = self._rows().order_by(
            Chat.is_pinned.desc(), Chat.updated_at.desc(), Chat.id
        )
        return [tuple(row) for row in (await self.session.exec(stmt)).all()]

    async def create_if_absent(self, contact_wa_id: str) -> None:
        """Race-safe: two concurrent opens of the same contact make one chat."""
        stmt = (
            insert(Chat)
            .values(id=uuid.uuid4(), contact_wa_id=contact_wa_id)
            .on_conflict_do_nothing(index_elements=["contact_wa_id"])
        )
        await self.session.exec(stmt)

    async def delete(self, chat_id: uuid.UUID) -> bool:
        """Cascades to the chat's messages."""
        stmt = delete(Chat).where(Chat.id == chat_id).returning(Chat.id)
        return (await self.session.exec(stmt)).scalar_one_or_none() is not None

    async def set_last_message(
        self, chat: Chat, message_id: uuid.UUID | None, *, touch: bool
    ) -> Chat:
        """touch=True bumps updated_at (new activity reorders the chat list)."""
        chat.last_message_id = message_id
        if touch:
            chat.updated_at = utcnow()
        self.session.add(chat)
        await self.session.flush()
        return chat

    async def reset_after_clear(self, chat: Chat) -> Chat:
        chat.last_message_id = None
        chat.unread_count = 0
        self.session.add(chat)
        await self.session.flush()
        return chat

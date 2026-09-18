import uuid

import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from core.phone import to_wa_id
from errors.exceptions import NotFoundError
from modules.chats.models import Chat
from modules.chats.repository import ChatRepository, ChatRow
from modules.contacts.repository import ContactRepository
from modules.messages.repository import MessageRepository

logger = structlog.get_logger("chat_service")


class ChatService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        chats: ChatRepository,
        contacts: ContactRepository,
        messages: MessageRepository,
    ):
        self.session = session
        self.chats = chats
        self.contacts = contacts
        self.messages = messages

    async def get_chat(self, chat_id: uuid.UUID) -> Chat:
        chat = await self.chats.get(chat_id)
        if chat is None:
            raise NotFoundError("Chat not found")
        return chat

    async def list_chats(self) -> list[ChatRow]:
        """Pinned first, then most recently active."""
        return await self.chats.list_rows()

    async def open_chat(self, wa_id: str) -> ChatRow:
        """Find-or-create the chat with an EXISTING contact."""
        wa_id = to_wa_id(wa_id)
        if await self.contacts.get(wa_id) is None:
            raise NotFoundError("Contact not found. Add the contact first.")

        await self.chats.create_if_absent(wa_id)
        await self.session.commit()

        row = await self.chats.get_row_by_contact(wa_id)
        if row is None:
            # the contact was deleted between the insert and this read
            raise NotFoundError("Contact not found")
        return row

    async def delete_chat(self, chat_id: uuid.UUID) -> None:
        """Local only — the Cloud API cannot delete from the customer's phone."""
        if not await self.chats.delete(chat_id):
            await self.session.rollback()
            raise NotFoundError("Chat not found")
        await self.session.commit()
        logger.info("chat_deleted", chat_id=str(chat_id))

    async def clear_chat(self, chat_id: uuid.UUID) -> None:
        """Delete every message but keep the chat row. Local only."""
        chat = await self.get_chat(chat_id)
        await self.chats.reset_after_clear(chat)
        await self.messages.delete_by_chat(chat.id)
        await self.session.commit()
        logger.info("chat_cleared", chat_id=str(chat_id))

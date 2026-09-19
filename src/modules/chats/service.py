import uuid

import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from core.phone import to_wa_id
from errors.exceptions import NotFoundError
from integrations.meta.client import MetaClient
from integrations.meta.errors import MetaApiError
from modules.business.repository import BusinessRepository
from modules.chats.models import Chat
from modules.chats.repository import ChatRepository, ChatRow
from modules.contacts.repository import ContactRepository
from modules.messages.repository import MessageRepository
from realtime import events as ws_events
from realtime.manager import ws_manager

logger = structlog.get_logger("chat_service")


class ChatService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        chats: ChatRepository,
        contacts: ContactRepository,
        messages: MessageRepository,
        business: BusinessRepository,
        meta: MetaClient,
    ):
        self.session = session
        self.chats = chats
        self.contacts = contacts
        self.messages = messages
        self.business = business
        self.meta = meta

    async def mark_read(self, chat_id: uuid.UUID) -> None:
        """The operator opened the chat: unread -> 0, inbound -> read, and
        blue ticks for the customer.

        Local state is committed first; a Meta failure is logged, not
        raised — the operator's read state must not depend on Meta.
        """
        chat = await self.get_chat(chat_id)
        changed = await self.messages.mark_inbound_read(chat.id)
        wamid = await self.messages.newest_inbound_wamid(chat.id)
        had_unread = chat.unread_count > 0
        if had_unread:
            chat.unread_count = 0
            await self.chats.save(chat)
        await self.session.commit()
        if had_unread or changed:
            # other devices drop the unread badge
            await self._publish_chat(chat.id)

        # nothing newly read -> no Meta call (reopening a read chat is free)
        if not changed or wamid is None:
            return
        business = await self.business.get()
        try:
            await self.meta.mark_read(
                phone_number_id=business.phone_number_id, wamid=wamid
            )
        except MetaApiError as e:
            logger.warning("meta_mark_read_failed", chat_id=str(chat_id), code=e.code)
            return
        logger.info("chat_marked_read", chat_id=str(chat_id), messages=changed)

    async def _publish_chat(self, chat_id: uuid.UUID) -> None:
        """chat.updated with the committed state."""
        row = await self.chats.get_row(chat_id)
        if row is not None:
            await ws_manager.publish(ws_events.chat_updated(row))

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
        await ws_manager.publish(ws_events.chat_deleted(chat_id))

    async def clear_chat(self, chat_id: uuid.UUID) -> None:
        """Delete every message but keep the chat row. Local only."""
        chat = await self.get_chat(chat_id)
        await self.chats.reset_after_clear(chat)
        await self.messages.delete_by_chat(chat.id)
        await self.session.commit()
        logger.info("chat_cleared", chat_id=str(chat_id))
        await self._publish_chat(chat.id)

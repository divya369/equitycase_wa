import uuid
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from errors.exceptions import NotFoundError
from modules.chats.repository import ChatRepository
from modules.messages.models import Message
from modules.messages.repository import MessageRepository


class MessageService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        chats: ChatRepository,
        messages: MessageRepository,
    ):
        self.session = session
        self.chats = chats
        self.messages = messages

    async def list_messages(
        self, chat_id: uuid.UUID, *, before: datetime | None, limit: int
    ) -> list[Message]:
        """One page, oldest first. Page back by passing the first item's time."""
        if await self.chats.get(chat_id) is None:
            raise NotFoundError("Chat not found")
        if before is not None and before.tzinfo is None:
            before = before.replace(tzinfo=UTC)
        return await self.messages.list_page(chat_id, before=before, limit=limit)

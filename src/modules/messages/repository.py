import uuid
from datetime import datetime

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.messages.models import Message


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_page(
        self, chat_id: uuid.UUID, *, before: datetime | None, limit: int
    ) -> list[Message]:
        """The `limit` newest messages older than `before`, OLDEST FIRST."""
        stmt = select(Message).where(Message.chat_id == chat_id)
        if before is not None:
            stmt = stmt.where(Message.created_at < before)
        stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
        rows = list((await self.session.exec(stmt)).all())
        rows.reverse()
        return rows

    async def delete_by_chat(self, chat_id: uuid.UUID) -> None:
        await self.session.exec(delete(Message).where(Message.chat_id == chat_id))

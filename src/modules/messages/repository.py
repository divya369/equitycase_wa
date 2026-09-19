import uuid
from datetime import datetime

from sqlmodel import delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.messages.models import Message, MessageStatus


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, message_id: uuid.UUID) -> Message | None:
        return await self.session.get(Message, message_id)

    async def get_by_client_msg_id(
        self, chat_id: uuid.UUID, client_msg_id: str
    ) -> Message | None:
        stmt = select(Message).where(
            Message.chat_id == chat_id, Message.client_msg_id == client_msg_id
        )
        return (await self.session.exec(stmt)).first()

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

    async def newest_id(self, chat_id: uuid.UUID) -> uuid.UUID | None:
        stmt = (
            select(Message.id)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        return (await self.session.exec(stmt)).first()

    async def create(self, message: Message) -> Message:
        """Raises IntegrityError on a duplicate (chat_id, client_msg_id)."""
        self.session.add(message)
        await self.session.flush()
        return message

    async def get_by_wamid(self, wamid: str) -> Message | None:
        stmt = select(Message).where(Message.wamid == wamid)
        return (await self.session.exec(stmt)).first()

    # -- status transitions: MONOTONIC (WHERE status < :new) -----------------
    async def advance_status(
        self, message_id: uuid.UUID, status: MessageStatus
    ) -> bool:
        """False when the message is already at or past `status` — Meta
        delivers webhooks out of order and a late 'sent' must not undo 'read'."""
        stmt = (
            update(Message)
            .where(Message.id == message_id, Message.status < status)
            .values(status=status)
        )
        return (await self.session.exec(stmt)).rowcount > 0

    async def mark_sent(self, message_id: uuid.UUID, wamid: str) -> bool:
        stmt = (
            update(Message)
            .where(Message.id == message_id, Message.status < MessageStatus.SENT)
            .values(wamid=wamid, status=MessageStatus.SENT)
        )
        return (await self.session.exec(stmt)).rowcount > 0

    async def mark_failed(
        self, message_id: uuid.UUID, *, code: int | None, title: str
    ) -> bool:
        stmt = (
            update(Message)
            .where(Message.id == message_id, Message.status < MessageStatus.FAILED)
            .values(status=MessageStatus.FAILED, error_code=code, error_title=title)
        )
        return (await self.session.exec(stmt)).rowcount > 0

    async def reset_for_retry(self, message_id: uuid.UUID) -> bool:
        """The ONE backwards move: failed -> pending (POST .../retry only)."""
        stmt = (
            update(Message)
            .where(Message.id == message_id, Message.status == MessageStatus.FAILED)
            .values(
                status=MessageStatus.PENDING,
                error_code=None,
                error_title=None,
                wamid=None,
            )
        )
        return (await self.session.exec(stmt)).rowcount > 0

    async def delete(self, chat_id: uuid.UUID, message_id: uuid.UUID) -> bool:
        stmt = (
            delete(Message)
            .where(Message.id == message_id, Message.chat_id == chat_id)
            .returning(Message.id)
        )
        return (await self.session.exec(stmt)).scalar_one_or_none() is not None

    async def delete_by_chat(self, chat_id: uuid.UUID) -> None:
        await self.session.exec(delete(Message).where(Message.chat_id == chat_id))

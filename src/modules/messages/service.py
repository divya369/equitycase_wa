import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from core.database import SessionFactory
from core.time import utcnow
from errors.exceptions import (
    ConflictError,
    ConversationWindowClosedError,
    NotFoundError,
)
from integrations.meta.client import MetaClient
from integrations.meta.errors import MetaApiError
from modules.business.repository import BusinessRepository
from modules.chats.models import Chat
from modules.chats.repository import ChatRepository
from modules.messages.models import Message, MessageDirection, MessageStatus
from modules.messages.repository import MessageRepository
from modules.webhook.processor import WebhookProcessor
from realtime import events as ws_events
from realtime.manager import ws_manager

logger = structlog.get_logger("message_service")

CUSTOMER_SERVICE_WINDOW = timedelta(hours=24)


def ensure_window_open(chat: Chat) -> None:
    """Free-form sends only within 24h of the customer's last inbound message."""
    if (
        chat.last_inbound_at is None
        or utcnow() - chat.last_inbound_at > CUSTOMER_SERVICE_WINDOW
    ):
        raise ConversationWindowClosedError()


class MessageService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        chats: ChatRepository,
        messages: MessageRepository,
        business: BusinessRepository,
    ):
        self.session = session
        self.chats = chats
        self.messages = messages
        self.business = business

    async def _get_chat(self, chat_id: uuid.UUID) -> Chat:
        chat = await self.chats.get(chat_id)
        if chat is None:
            raise NotFoundError("Chat not found")
        return chat

    async def list_messages(
        self, chat_id: uuid.UUID, *, before: datetime | None, limit: int
    ) -> list[Message]:
        """One page, oldest first. Page back by passing the first item's time."""
        await self._get_chat(chat_id)
        if before is not None and before.tzinfo is None:
            before = before.replace(tzinfo=UTC)
        return await self.messages.list_page(chat_id, before=before, limit=limit)

    async def send_text(
        self,
        chat_id: uuid.UUID,
        *,
        client_msg_id: str,
        body: str,
        reply_to_wamid: str | None,
    ) -> tuple[Message, bool]:
        """Store the message as PENDING. Returns (message, needs_delivery).

        Idempotent on (chat_id, client_msg_id): a repeat returns the existing
        row and needs no delivery. Meta is called afterwards, in the
        background (MessageDelivery).
        """
        chat = await self._get_chat(chat_id)

        existing = await self.messages.get_by_client_msg_id(chat_id, client_msg_id)
        if existing is not None:
            return existing, False

        ensure_window_open(chat)

        business = await self.business.get()
        message = Message(
            chat_id=chat_id,
            client_msg_id=client_msg_id,
            sender_wa_id=business.wa_id,
            direction=MessageDirection.OUT,
            type="text",
            body=body,
            reply_to_wamid=reply_to_wamid,
            status=MessageStatus.PENDING,
        )
        try:
            await self.messages.create(message)
            await self.chats.set_last_message(chat, message.id, touch=True)
            await self.session.commit()
        except IntegrityError:
            # a concurrent request with the same client_msg_id won the insert
            await self.session.rollback()
            existing = await self.messages.get_by_client_msg_id(chat_id, client_msg_id)
            if existing is None:
                raise
            return existing, False

        logger.info("message_queued", chat_id=str(chat_id), message_id=str(message.id))
        await self._publish_chat(chat_id)
        return message, True

    async def _publish_chat(self, chat_id: uuid.UUID) -> None:
        """chat.updated with the committed state (last_message / order)."""
        row = await self.chats.get_row(chat_id)
        if row is not None:
            await ws_manager.publish(ws_events.chat_updated(row))

    async def retry(self, message_id: uuid.UUID) -> Message:
        """failed -> pending, then redeliver. The ONLY backwards status move."""
        message = await self.messages.get(message_id)
        if message is None:
            raise NotFoundError("Message not found")
        if (
            message.direction != MessageDirection.OUT
            or message.status != MessageStatus.FAILED
        ):
            raise ConflictError("Only failed outgoing messages can be retried")

        ensure_window_open(await self._get_chat(message.chat_id))

        if not await self.messages.reset_for_retry(message_id):
            await self.session.rollback()
            raise ConflictError("Only failed outgoing messages can be retried")
        await self.session.commit()
        await self.session.refresh(message)

        logger.info("message_retry_queued", message_id=str(message_id))
        # other devices: failed -> pending
        await ws_manager.publish(ws_events.message_status(message))
        return message

    async def delete_message(self, chat_id: uuid.UUID, message_id: uuid.UUID) -> None:
        """Local only — the Cloud API cannot delete from the customer's phone."""
        chat = await self._get_chat(chat_id)
        if not await self.messages.delete(chat_id, message_id):
            await self.session.rollback()
            raise NotFoundError("Message not found")

        was_last = chat.last_message_id == message_id
        if was_last:
            newest = await self.messages.newest_id(chat_id)
            await self.chats.set_last_message(chat, newest, touch=False)
        await self.session.commit()
        logger.info("message_deleted", chat_id=str(chat_id), message_id=str(message_id))

        await ws_manager.publish(ws_events.message_deleted(chat_id, message_id))
        if was_last:
            await self._publish_chat(chat_id)


class MessageDelivery:
    """Sends a PENDING message to Meta after the HTTP response has gone out.

    Runs as a BackgroundTask, so it opens its OWN session — never reuse the
    request's session here.
    """

    def __init__(self, meta: MetaClient):
        self.meta = meta

    async def deliver(self, message_id: uuid.UUID) -> None:
        async with SessionFactory() as session:
            messages = MessageRepository(session)
            message = await messages.get(message_id)
            if message is None or message.status != MessageStatus.PENDING:
                return

            chat = await ChatRepository(session).get(message.chat_id)
            business = await BusinessRepository(session).get()

            try:
                wamid = await self.meta.send_text(
                    phone_number_id=business.phone_number_id,
                    to=chat.contact_wa_id,
                    body=message.body,
                    reply_to_wamid=message.reply_to_wamid,
                )
            except MetaApiError as e:
                await messages.mark_failed(message_id, code=e.code, title=e.title)
                await session.commit()
                logger.warning(
                    "message_send_failed",
                    message_id=str(message_id),
                    code=e.code,
                    window_closed=e.is_window_closed,
                )
                await self._publish_status(session, message)
                return
            except Exception:
                await session.rollback()
                await messages.mark_failed(
                    message_id, code=None, title="Could not send the message"
                )
                await session.commit()
                logger.exception("message_send_crashed", message_id=str(message_id))
                await self._publish_status(session, message)
                return

            await messages.mark_sent(message_id, wamid)
            await session.commit()
            logger.info("message_sent", message_id=str(message_id))
            await self._publish_status(session, message)

        # a 'delivered'/'read' webhook may have beaten our own commit above
        await WebhookProcessor().process_pending_statuses(wamid)

    @staticmethod
    async def _publish_status(session: AsyncSession, message: Message) -> None:
        """message.status with the committed row (sent / failed + error)."""
        await session.refresh(message)
        await ws_manager.publish(ws_events.message_status(message))

"""Inbound customer messages (webhook `messages[]`) -> contact, chat, message.

Runs inside WebhookProcessor, in the processor's own session. The caller
commits, then publishes `events` and sends `pushes`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from core.phone import to_display_phone
from core.time import utcnow
from modules.chats.models import Chat
from modules.chats.repository import ChatRepository
from modules.contacts.models import Contact
from modules.contacts.repository import ContactRepository
from modules.messages.models import Message, MessageDirection, MessageStatus
from modules.messages.repository import MessageRepository
from modules.notifications.service import InboundPush
from realtime import events as ws_events
from realtime.manager import WsEvent

logger = structlog.get_logger("webhook_inbound")

# Types the Flutter client renders. Anything else is stored as text.
MEDIA_TYPES = {"image", "video", "audio", "document", "sticker"}
# Not a chat message: reactions, number-change notices, etc.
SKIPPED_TYPES = {"reaction", "system", "ephemeral", "request_welcome"}
UNSUPPORTED_BODY = "[Unsupported message]"


@dataclass
class ParsedMessage:
    type: str
    body: str
    media_id: str | None = None
    media_mime: str | None = None


def parse_message(message: dict[str, Any]) -> ParsedMessage | None:
    """Meta's message object -> what we store. None = not a chat message."""
    kind = message.get("type") or ""
    if kind in SKIPPED_TYPES:
        return None

    if kind == "text":
        return ParsedMessage("text", (message.get("text") or {}).get("body") or "")

    if kind in MEDIA_TYPES:
        media = message.get(kind) or {}
        caption = media.get("caption") or (
            media.get("filename") if kind == "document" else ""
        )
        # the file itself is downloaded to R2 in P10; media_url stays null
        return ParsedMessage(
            kind,
            caption or "",
            media_id=media.get("id"),
            media_mime=media.get("mime_type"),
        )

    if kind == "location":
        location = message.get("location") or {}
        label = location.get("name") or location.get("address") or ""
        return ParsedMessage("location", label or "📍 Location")

    if kind == "button":
        return ParsedMessage("text", (message.get("button") or {}).get("text") or "")

    if kind == "interactive":
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return ParsedMessage("text", reply.get("title") or UNSUPPORTED_BODY)

    return ParsedMessage("text", UNSUPPORTED_BODY)


def message_time(message: dict[str, Any]) -> datetime:
    """Meta's unix-seconds timestamp; never in the future."""
    now = utcnow()
    try:
        sent_at = datetime.fromtimestamp(int(message["timestamp"]), UTC)
    except KeyError, TypeError, ValueError, OverflowError, OSError:
        return now
    return min(sent_at, now)


def profile_name(contacts: list[dict[str, Any]], wa_id: str) -> str | None:
    for contact in contacts:
        if contact.get("wa_id") == wa_id:
            name = ((contact.get("profile") or {}).get("name") or "").strip()
            return name or None
    return None


class InboundMessageHandler:
    def __init__(self, session: AsyncSession):
        self.contacts = ContactRepository(session)
        self.chats = ChatRepository(session)
        self.messages = MessageRepository(session)
        # WS events + FCM pushes for the caller to send after its commit
        self.events: list[WsEvent] = []
        self.pushes: list[InboundPush] = []

    async def handle(
        self, message: dict[str, Any], contacts: list[dict[str, Any]]
    ) -> Message | None:
        """Returns the new message; None when skipped or already stored."""
        wa_id = message.get("from")
        wamid = message.get("id")
        parsed = parse_message(message)
        if not wa_id or not wamid or parsed is None:
            logger.info("inbound_message_skipped", type=message.get("type"))
            return None

        contact = await self._upsert_contact(wa_id, profile_name(contacts, wa_id))
        chat = await self._lock_chat(wa_id)

        # dedupe under the chat lock: a wamid always belongs to this chat
        if await self.messages.get_by_wamid(wamid) is not None:
            logger.info("inbound_message_duplicate", chat_id=str(chat.id))
            return None

        sent_at = message_time(message)
        stored = await self.messages.create(
            Message(
                chat_id=chat.id,
                wamid=wamid,
                sender_wa_id=wa_id,
                direction=MessageDirection.IN,
                type=parsed.type,
                body=parsed.body,
                media_id=parsed.media_id,
                media_mime=parsed.media_mime,
                reply_to_wamid=(message.get("context") or {}).get("id"),
                # inbound read state is ours: 'read' only when the operator
                # opens the chat (POST /v1/chats/{id}/read)
                status=MessageStatus.DELIVERED,
                created_at=sent_at,
            )
        )
        await self._record_on_chat(chat, stored)

        logger.info(
            "inbound_message_stored",
            chat_id=str(chat.id),
            message_id=str(stored.id),
            type=parsed.type,
        )
        self.events.append(ws_events.message_new(stored))
        self.events.append(ws_events.chat_updated(await self.chats.get_row(chat.id)))
        self.pushes.append(InboundPush.build(chat, contact, stored))
        return stored

    async def _upsert_contact(self, wa_id: str, name: str | None) -> Contact:
        phone = to_display_phone(wa_id)
        contact = await self.contacts.create_if_absent(
            wa_id=wa_id, name=name or phone, phone=phone
        )
        if contact is not None:
            logger.info("inbound_contact_created")
            return contact

        contact = await self.contacts.get(wa_id)
        # only replace the placeholder — never a name the operator chose
        if name and contact.name in {contact.phone, contact.wa_id, phone}:
            contact = await self.contacts.update_name(contact, name)
        return contact

    async def _lock_chat(self, wa_id: str) -> Chat:
        await self.chats.create_if_absent(wa_id)
        return await self.chats.get_by_contact_for_update(wa_id)

    async def _record_on_chat(self, chat: Chat, message: Message) -> None:
        chat.unread_count += 1
        # the 24h customer-service window runs from the customer's message
        if chat.last_inbound_at is None or message.created_at > chat.last_inbound_at:
            chat.last_inbound_at = message.created_at

        current = (
            await self.messages.get(chat.last_message_id)
            if chat.last_message_id
            else None
        )
        # webhooks can arrive out of order: only a NEWER message becomes last
        # (and only that is new activity that moves the chat to the top —
        # Meta's timestamps are whole seconds, so "now" breaks the ties)
        if current is None or message.created_at >= current.created_at:
            chat.last_message_id = message.id
            chat.updated_at = utcnow()
        await self.chats.save(chat)

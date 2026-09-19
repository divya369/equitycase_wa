"""Push notifications (FCM) for inbound customer messages.

Runs after the webhook event's commit, in its OWN session. Never raises —
a push is best-effort and must not fail webhook processing.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from core.database import SessionFactory
from core.time import utcnow
from integrations.fcm.client import get_fcm_client
from modules.chats.models import Chat
from modules.contacts.models import Contact
from modules.messages.models import Message
from modules.operator.repository import FcmTokenRepository
from realtime.manager import ws_manager

logger = structlog.get_logger("push_service")

# a replayed webhook (server was down) is not news any more
MAX_PUSH_AGE = timedelta(hours=1)

# media: the label, plus the caption when there is one
MEDIA_PREVIEW = {
    "image": "📷 Photo",
    "video": "🎥 Video",
    "audio": "🎵 Audio",
    "document": "📄 Document",
    "sticker": "Sticker",
}


@dataclass(frozen=True)
class InboundPush:
    """What the Flutter client's PushMessage parses — all strings."""

    chat_id: str
    sender_id: str
    sender_name: str
    body: str
    is_muted: bool
    sent_at: datetime

    @classmethod
    def build(cls, chat: Chat, contact: Contact, message: Message) -> InboundPush:
        label = MEDIA_PREVIEW.get(message.type)
        if label is None:
            body = message.body or "New message"
        else:
            body = f"{label}: {message.body}" if message.body else label
        return cls(
            chat_id=str(chat.id),
            sender_id=contact.wa_id,
            sender_name=contact.name,
            body=body,
            is_muted=chat.is_muted,
            sent_at=message.created_at,
        )

    def data(self) -> dict[str, str]:
        return {
            "chat_id": self.chat_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "body": self.body,
        }


class PushService:
    async def notify_inbound(self, push: InboundPush) -> None:
        try:
            await self._notify(push)
        except Exception:
            logger.exception("push_failed", chat_id=push.chat_id)

    async def _notify(self, push: InboundPush) -> None:
        # the operator is in the app: WS already delivered it
        if ws_manager.has_clients:
            logger.info("push_skipped", reason="ws_connected")
            return
        if push.is_muted:
            logger.info("push_skipped", reason="muted", chat_id=push.chat_id)
            return
        if utcnow() - push.sent_at > MAX_PUSH_AGE:
            logger.info("push_skipped", reason="stale", chat_id=push.chat_id)
            return
        client = get_fcm_client()
        if client is None:
            return

        async with SessionFactory() as session:
            tokens = await FcmTokenRepository(session).list_tokens()
        if not tokens:
            logger.info("push_skipped", reason="no_devices")
            return

        dead = await client.send_data(tokens, push.data())
        if dead:
            async with SessionFactory() as session:
                await FcmTokenRepository(session).delete_many(dead)
                await session.commit()
            logger.info("fcm_tokens_removed", count=len(dead))

"""Import every table model here so Alembic autogenerate sees it."""

from sqlmodel import SQLModel

from modules.auth.models import OtpCode
from modules.business.models import BusinessNumber
from modules.chats.models import Chat
from modules.contacts.models import Contact
from modules.marketing.models import MarketingOptOut
from modules.messages.models import Message
from modules.operator.models import FcmToken, Operator
from modules.webhook.models import WebhookEvent

__all__ = [
    "SQLModel",
    "BusinessNumber",
    "Chat",
    "Contact",
    "FcmToken",
    "MarketingOptOut",
    "Message",
    "Operator",
    "OtpCode",
    "WebhookEvent",
]

import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from core.phone import to_display_phone, to_wa_id
from errors.exceptions import ConflictError, NotFoundError
from modules.chats.repository import ChatRepository
from modules.contacts.models import Contact
from modules.contacts.repository import ContactRepository
from realtime import events as ws_events
from realtime.manager import ws_manager

logger = structlog.get_logger("contact_service")


class ContactService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        contacts: ContactRepository,
        chats: ChatRepository,
    ):
        self.session = session
        self.contacts = contacts
        self.chats = chats

    async def list_contacts(self) -> list[Contact]:
        return await self.contacts.list_all()

    async def create_contact(self, *, name: str, phone: str) -> Contact:
        """A DB row only — the customer still has to message the business
        number first before free-form text can be sent (24h window)."""
        contact = await self.contacts.create_if_absent(
            wa_id=to_wa_id(phone), name=name, phone=to_display_phone(phone)
        )
        if contact is None:
            await self.session.rollback()
            raise ConflictError("A contact with this phone number already exists")
        await self.session.commit()
        logger.info("contact_created")
        return contact

    async def delete_contact(self, wa_id: str) -> None:
        """Local only. Cascades to the contact's chat and its messages."""
        chat = await self.chats.get_row_by_contact(wa_id)
        if not await self.contacts.delete(wa_id):
            await self.session.rollback()
            raise NotFoundError("Contact not found")
        await self.session.commit()
        logger.info("contact_deleted")
        if chat is not None:
            await ws_manager.publish(ws_events.chat_deleted(chat[0].id))

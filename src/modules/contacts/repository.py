from sqlalchemy.dialects.postgresql import insert
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.contacts.models import Contact


class ContactRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, wa_id: str) -> Contact | None:
        return await self.session.get(Contact, wa_id)

    async def list_all(self) -> list[Contact]:
        stmt = select(Contact).order_by(Contact.name, Contact.wa_id)
        return list((await self.session.exec(stmt)).all())

    async def create_if_absent(
        self, *, wa_id: str, name: str, phone: str
    ) -> Contact | None:
        """Insert, or return None when the wa_id already exists."""
        stmt = (
            insert(Contact)
            .values(wa_id=wa_id, name=name, phone=phone)
            .on_conflict_do_nothing(index_elements=["wa_id"])
            .returning(Contact)
        )
        return (await self.session.exec(stmt)).scalar_one_or_none()

    async def update_name(self, contact: Contact, name: str) -> Contact:
        contact.name = name
        self.session.add(contact)
        await self.session.flush()
        return contact

    async def delete(self, wa_id: str) -> bool:
        stmt = delete(Contact).where(Contact.wa_id == wa_id).returning(Contact.wa_id)
        return (await self.session.exec(stmt)).scalar_one_or_none() is not None

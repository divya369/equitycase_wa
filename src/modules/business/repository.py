from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.business.models import BusinessNumber


class BusinessRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self) -> BusinessNumber | None:
        return await self.session.get(BusinessNumber, 1)

    async def upsert(
        self,
        *,
        phone_number_id: str,
        waba_id: str | None,
        display_phone: str,
        verified_name: str,
    ) -> None:
        values = {
            "phone_number_id": phone_number_id,
            "waba_id": waba_id,
            "display_phone": display_phone,
            "verified_name": verified_name,
        }
        stmt = insert(BusinessNumber).values(id=1, **values)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=values)
        await self.session.exec(stmt)

from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.operator.models import Operator


class OperatorRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self) -> Operator | None:
        return await self.session.get(Operator, 1)

    async def upsert(self, *, phone: str, wa_id: str, name: str) -> None:
        values = {"phone": phone, "wa_id": wa_id, "name": name}
        stmt = insert(Operator).values(id=1, **values)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=values)
        await self.session.exec(stmt)

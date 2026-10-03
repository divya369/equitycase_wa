from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.marketing.models import MarketingOptOut


class MarketingOptOutRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, wa_id: str) -> MarketingOptOut | None:
        return await self.session.get(MarketingOptOut, wa_id)

    async def add(self, *, wa_id: str, source: str) -> None:
        """Idempotent: a second STOP keeps the first row (and its date)."""
        stmt = insert(MarketingOptOut).values(wa_id=wa_id, source=source)
        await self.session.exec(stmt.on_conflict_do_nothing(index_elements=["wa_id"]))

    async def remove(self, wa_id: str) -> None:
        await self.session.exec(
            delete(MarketingOptOut).where(MarketingOptOut.wa_id == wa_id)
        )

    async def list_all(self) -> list[MarketingOptOut]:
        stmt = select(MarketingOptOut).order_by(col(MarketingOptOut.created_at).desc())
        return list((await self.session.exec(stmt)).all())

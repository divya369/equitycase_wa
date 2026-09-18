from sqlalchemy.dialects.postgresql import insert
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from core.time import utcnow
from modules.operator.models import FcmToken, Operator


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

    async def update_name(self, operator: Operator, name: str) -> Operator:
        operator.name = name
        self.session.add(operator)
        await self.session.flush()
        return operator


class FcmTokenRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, *, token: str, platform: str) -> None:
        stmt = insert(FcmToken).values(
            token=token, platform=platform, updated_at=utcnow()
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["token"],
            set_={"platform": platform, "updated_at": utcnow()},
        )
        await self.session.exec(stmt)

    async def delete(self, token: str) -> None:
        await self.session.exec(delete(FcmToken).where(FcmToken.token == token))

    async def list_tokens(self) -> list[str]:
        return list((await self.session.exec(select(FcmToken.token))).all())

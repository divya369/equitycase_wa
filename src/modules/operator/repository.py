from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from core.security import SEEDED_OPERATOR_ID
from core.time import utcnow
from modules.operator.models import FcmToken, Operator


class OperatorRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, operator_id: int = SEEDED_OPERATOR_ID) -> Operator | None:
        return await self.session.get(Operator, operator_id)

    async def get_by_wa_id(self, wa_id: str) -> Operator | None:
        stmt = select(Operator).where(Operator.wa_id == wa_id)
        return (await self.session.exec(stmt)).first()

    async def list_all(self) -> list[Operator]:
        stmt = select(Operator).order_by(col(Operator.id))
        return list((await self.session.exec(stmt)).all())

    async def upsert_seeded(self, *, phone: str, wa_id: str, name: str) -> None:
        """`make seed` only: the singleton row id = 1."""
        values = {"phone": phone, "wa_id": wa_id, "name": name}
        stmt = insert(Operator).values(id=SEEDED_OPERATOR_ID, **values)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=values)
        await self.session.exec(stmt)

    async def create(self, *, phone: str, wa_id: str, name: str) -> Operator:
        operator = Operator(phone=phone, wa_id=wa_id, name=name)
        self.session.add(operator)
        await self.session.flush()
        return operator

    async def delete(self, operator: Operator) -> None:
        await self.session.delete(operator)

    async def update_name(self, operator: Operator, name: str) -> Operator:
        operator.name = name
        self.session.add(operator)
        await self.session.flush()
        return operator


class FcmTokenRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, *, token: str, platform: str, operator_id: int) -> None:
        """A device that logs in as someone else moves to that operator."""
        stmt = insert(FcmToken).values(
            token=token,
            platform=platform,
            operator_id=operator_id,
            updated_at=utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["token"],
            set_={
                "platform": platform,
                "operator_id": operator_id,
                "updated_at": utcnow(),
            },
        )
        await self.session.exec(stmt)

    async def delete(self, token: str) -> None:
        await self.session.exec(delete(FcmToken).where(FcmToken.token == token))

    async def delete_many(self, tokens: list[str]) -> None:
        await self.session.exec(delete(FcmToken).where(FcmToken.token.in_(tokens)))

    async def list_tokens(self) -> list[str]:
        return list((await self.session.exec(select(FcmToken.token))).all())

    async def list_tokens_except(self, operator_ids: set[int]) -> list[str]:
        """Devices of the operators who are NOT on a WebSocket right now."""
        stmt = select(FcmToken.token)
        if operator_ids:
            stmt = stmt.where(col(FcmToken.operator_id).notin_(operator_ids))
        return list((await self.session.exec(stmt)).all())

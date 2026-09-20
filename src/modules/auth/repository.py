from datetime import datetime

from sqlmodel import col, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from core.time import utcnow
from modules.auth.models import OtpCode


class OtpRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, *, operator_id: int, code_hash: str, expires_at: datetime
    ) -> OtpCode:
        otp = OtpCode(
            operator_id=operator_id, code_hash=code_hash, expires_at=expires_at
        )
        self.session.add(otp)
        await self.session.flush()
        return otp

    async def get_newest_active_for_update(self, operator_id: int) -> OtpCode | None:
        """Newest unconsumed, unexpired code, row-locked for the verify attempt."""
        stmt = (
            select(OtpCode)
            .where(OtpCode.operator_id == operator_id)
            .where(col(OtpCode.consumed_at).is_(None))
            .where(OtpCode.expires_at > utcnow())
            .order_by(col(OtpCode.created_at).desc())
            .limit(1)
            .with_for_update()
        )
        return (await self.session.exec(stmt)).first()

    async def invalidate_active(self, operator_id: int) -> None:
        """Consume this operator's outstanding codes; another operator's
        pending login is untouched."""
        stmt = (
            update(OtpCode)
            .where(OtpCode.operator_id == operator_id)
            .where(col(OtpCode.consumed_at).is_(None))
            .values(consumed_at=utcnow())
        )
        await self.session.exec(stmt)

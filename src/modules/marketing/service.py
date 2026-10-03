"""Marketing opt-outs: who must not receive a marketing blast.

The STOP button under a marketing template arrives on the webhook like any
other inbound message; `is_stop_request` recognises it, and the inbound
handler records the opt-out in the same transaction as the message.
"""

import structlog
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.marketing.models import MarketingOptOut
from modules.marketing.repository import MarketingOptOutRepository

logger = structlog.get_logger("marketing_service")

# What the STOP button (and people typing it) sends. Compared case- and
# punctuation-insensitively against the whole message.
STOP_WORDS = {
    "stop",
    "stopall",
    "unsubscribe",
    "optout",
    "opt out",
    "stop promo",
    "stop promotions",
}

SOURCE_BUTTON = "stop_button"
SOURCE_TEXT = "stop_text"
SOURCE_MANUAL = "manual"


def is_stop_request(body: str) -> bool:
    """True for "STOP", "Stop.", "unsubscribe" — not for a sentence that
    merely contains the word."""
    cleaned = body.strip().strip(".!,;:").casefold()
    return cleaned in STOP_WORDS


class MarketingService:
    def __init__(
        self, *, session: AsyncSession, opt_outs: MarketingOptOutRepository
    ) -> None:
        self.session = session
        self.opt_outs = opt_outs

    async def status(self, wa_id: str) -> MarketingOptOut | None:
        return await self.opt_outs.get(wa_id)

    async def opt_out(self, wa_id: str, *, source: str = SOURCE_MANUAL) -> None:
        await self.opt_outs.add(wa_id=wa_id, source=source)
        await self.session.commit()
        logger.info("marketing_opt_out_added", source=source)

    async def opt_in(self, wa_id: str) -> None:
        """Only on an explicit request from the customer."""
        await self.opt_outs.remove(wa_id)
        await self.session.commit()
        logger.info("marketing_opt_out_removed")

    async def list_opt_outs(self) -> list[MarketingOptOut]:
        return await self.opt_outs.list_all()

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from modules.marketing.models import MarketingOptOut


class OptOutStatusOut(BaseModel):
    """The blast CLI reads `opted_out`: true = do NOT send."""

    wa_id: str
    opted_out: bool
    source: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_model(cls, wa_id: str, row: MarketingOptOut | None) -> OptOutStatusOut:
        if row is None:
            return cls(wa_id=wa_id, opted_out=False)
        return cls(
            wa_id=wa_id,
            opted_out=True,
            source=row.source,
            created_at=row.created_at,
        )

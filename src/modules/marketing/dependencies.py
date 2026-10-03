from typing import Annotated

from fastapi import Depends, Header

from config.app_config import app_config
from core.database import SessionDep
from core.security import constant_time_equals
from errors.exceptions import UnauthorizedError
from modules.marketing.repository import MarketingOptOutRepository
from modules.marketing.service import MarketingService


def require_marketing_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Shared-key auth for the blast CLI — it has no operator JWT.

    No key configured = the endpoints stay shut (401), never open.
    """
    configured = app_config.marketing_api_key
    if configured is None:
        raise UnauthorizedError("Marketing API key is not configured")
    if not x_api_key or not constant_time_equals(
        x_api_key, configured.get_secret_value()
    ):
        raise UnauthorizedError("Invalid API key")


def get_marketing_service(session: SessionDep) -> MarketingService:
    return MarketingService(
        session=session, opt_outs=MarketingOptOutRepository(session)
    )


MarketingServiceDep = Annotated[MarketingService, Depends(get_marketing_service)]
MarketingApiKey = Depends(require_marketing_api_key)

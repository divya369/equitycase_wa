from typing import Annotated

from fastapi import Depends

from core.database import SessionDep
from modules.business.repository import BusinessRepository
from modules.webhook.processor import WebhookProcessor
from modules.webhook.repository import WebhookEventRepository
from modules.webhook.service import WebhookService


def get_webhook_service(session: SessionDep) -> WebhookService:
    return WebhookService(
        session=session,
        events=WebhookEventRepository(session),
        business=BusinessRepository(session),
    )


def get_webhook_processor() -> WebhookProcessor:
    return WebhookProcessor()


WebhookServiceDep = Annotated[WebhookService, Depends(get_webhook_service)]
WebhookProcessorDep = Annotated[WebhookProcessor, Depends(get_webhook_processor)]

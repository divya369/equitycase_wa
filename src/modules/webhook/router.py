"""Meta webhook. External contract — exempt from the {data, meta} envelope.

No JWT: GET is protected by META_VERIFY_TOKEN, POST by X-Hub-Signature-256.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from fastapi.responses import PlainTextResponse

from modules.webhook.dependencies import WebhookProcessorDep, WebhookServiceDep

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.get("", response_class=PlainTextResponse)
async def verify_webhook(
    service: WebhookServiceDep,
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> PlainTextResponse:
    return PlainTextResponse(
        service.verify_subscription(
            mode=mode, verify_token=verify_token, challenge=challenge
        )
    )


@router.post("")
async def receive_webhook(
    request: Request,
    service: WebhookServiceDep,
    processor: WebhookProcessorDep,
    background: BackgroundTasks,
) -> Response:
    # RAW bytes first — no Pydantic body param, the signature covers them
    body = await request.body()
    keys = await service.receive(body, request.headers.get("X-Hub-Signature-256"))
    if keys:
        background.add_task(processor.process, keys)
    return Response(status_code=200)

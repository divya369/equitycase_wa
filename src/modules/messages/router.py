import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Response, status

from core.responses import ApiResponse, MetaDep
from modules.messages.dependencies import MessageDeliveryDep, MessageServiceDep
from modules.messages.schemas import MessageOut, SendMessageIn

router = APIRouter(tags=["messages"])


@router.get("/chats/{chat_id}/messages", response_model=ApiResponse[list[MessageOut]])
async def list_messages(
    chat_id: uuid.UUID,
    service: MessageServiceDep,
    meta: MetaDep,
    before: Annotated[
        datetime | None,
        Query(description="ISO-8601; only messages older than this"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ApiResponse[list[MessageOut]]:
    messages = await service.list_messages(chat_id, before=before, limit=limit)
    return ApiResponse(data=[MessageOut.from_model(m) for m in messages], meta=meta)


@router.post(
    "/chats/{chat_id}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[MessageOut],
)
async def send_message(
    chat_id: uuid.UUID,
    body: SendMessageIn,
    service: MessageServiceDep,
    delivery: MessageDeliveryDep,
    background: BackgroundTasks,
    meta: MetaDep,
) -> ApiResponse[MessageOut]:
    """Returns the PENDING row at once; Meta is called after the response."""
    message, needs_delivery = await service.send_text(
        chat_id,
        client_msg_id=body.client_msg_id,
        body=body.body,
        reply_to_wamid=body.context.id if body.context else None,
    )
    if needs_delivery:
        background.add_task(delivery.deliver, message.id)
    return ApiResponse(data=MessageOut.from_model(message), meta=meta)


@router.post("/messages/{message_id}/retry", response_model=ApiResponse[MessageOut])
async def retry_message(
    message_id: uuid.UUID,
    service: MessageServiceDep,
    delivery: MessageDeliveryDep,
    background: BackgroundTasks,
    meta: MetaDep,
) -> ApiResponse[MessageOut]:
    message = await service.retry(message_id)
    background.add_task(delivery.deliver, message.id)
    return ApiResponse(data=MessageOut.from_model(message), meta=meta)


@router.delete(
    "/chats/{chat_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_message(
    chat_id: uuid.UUID, message_id: uuid.UUID, service: MessageServiceDep
) -> Response:
    await service.delete_message(chat_id, message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

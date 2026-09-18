import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from core.responses import ApiResponse, MetaDep
from modules.messages.dependencies import MessageServiceDep
from modules.messages.schemas import MessageOut

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

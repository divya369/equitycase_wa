import uuid

from fastapi import APIRouter, Response, status

from core.responses import ApiResponse, MetaDep
from modules.chats.dependencies import ChatServiceDep
from modules.chats.schemas import ChatOut, OpenChatIn

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=ApiResponse[list[ChatOut]])
async def list_chats(
    service: ChatServiceDep, meta: MetaDep
) -> ApiResponse[list[ChatOut]]:
    rows = await service.list_chats()
    return ApiResponse(data=[ChatOut.from_models(*row) for row in rows], meta=meta)


@router.post("", response_model=ApiResponse[ChatOut])
async def open_chat(
    body: OpenChatIn, service: ChatServiceDep, meta: MetaDep
) -> ApiResponse[ChatOut]:
    row = await service.open_chat(body.wa_id)
    return ApiResponse(data=ChatOut.from_models(*row), meta=meta)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(chat_id: uuid.UUID, service: ChatServiceDep) -> Response:
    await service.delete_chat(chat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{chat_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_chat_read(chat_id: uuid.UUID, service: ChatServiceDep) -> Response:
    await service.mark_read(chat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{chat_id}/clear", status_code=status.HTTP_204_NO_CONTENT)
async def clear_chat(chat_id: uuid.UUID, service: ChatServiceDep) -> Response:
    await service.clear_chat(chat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

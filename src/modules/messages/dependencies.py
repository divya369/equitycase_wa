from typing import Annotated

from fastapi import Depends

from core.database import SessionDep
from modules.chats.repository import ChatRepository
from modules.messages.repository import MessageRepository
from modules.messages.service import MessageService


def get_message_service(session: SessionDep) -> MessageService:
    return MessageService(
        session=session,
        chats=ChatRepository(session),
        messages=MessageRepository(session),
    )


MessageServiceDep = Annotated[MessageService, Depends(get_message_service)]

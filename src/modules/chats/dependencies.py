from typing import Annotated

from fastapi import Depends

from core.database import SessionDep
from modules.chats.repository import ChatRepository
from modules.chats.service import ChatService
from modules.contacts.repository import ContactRepository
from modules.messages.repository import MessageRepository


def get_chat_service(session: SessionDep) -> ChatService:
    return ChatService(
        session=session,
        chats=ChatRepository(session),
        contacts=ContactRepository(session),
        messages=MessageRepository(session),
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]

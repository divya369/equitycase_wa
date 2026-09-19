from typing import Annotated

from fastapi import Depends

from core.database import SessionDep
from integrations.meta.dependencies import MetaClientDep
from modules.business.repository import BusinessRepository
from modules.chats.repository import ChatRepository
from modules.chats.service import ChatService
from modules.contacts.repository import ContactRepository
from modules.messages.repository import MessageRepository


def get_chat_service(session: SessionDep, meta: MetaClientDep) -> ChatService:
    return ChatService(
        session=session,
        chats=ChatRepository(session),
        contacts=ContactRepository(session),
        messages=MessageRepository(session),
        business=BusinessRepository(session),
        meta=meta,
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]

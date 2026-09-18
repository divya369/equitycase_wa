from typing import Annotated

from fastapi import Depends

from core.database import SessionDep
from integrations.meta.dependencies import MetaClientDep
from modules.business.repository import BusinessRepository
from modules.chats.repository import ChatRepository
from modules.messages.repository import MessageRepository
from modules.messages.service import MessageDelivery, MessageService


def get_message_service(session: SessionDep) -> MessageService:
    return MessageService(
        session=session,
        chats=ChatRepository(session),
        messages=MessageRepository(session),
        business=BusinessRepository(session),
    )


def get_message_delivery(meta: MetaClientDep) -> MessageDelivery:
    return MessageDelivery(meta)


MessageServiceDep = Annotated[MessageService, Depends(get_message_service)]
MessageDeliveryDep = Annotated[MessageDelivery, Depends(get_message_delivery)]

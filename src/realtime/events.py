"""WS event builders. Payloads come from the shared schema mappers, so a WS
frame carries exactly the JSON REST returns.

Build an event while the data is at hand, publish it only AFTER the commit —
a client that re-fetches on the event must see the new state.
"""

import uuid

from modules.chats.repository import ChatRow
from modules.chats.schemas import ChatOut
from modules.messages.models import Message
from modules.messages.schemas import MessageOut
from realtime.manager import WsEvent


def _json(model) -> dict:
    return model.model_dump(mode="json", by_alias=True)


def message_new(message: Message) -> WsEvent:
    return WsEvent("message.new", _json(MessageOut.from_model(message)))


def message_status(message: Message) -> WsEvent:
    out = MessageOut.from_model(message)
    return WsEvent(
        "message.status",
        {
            "id": str(out.id),
            "wamid": message.wamid,
            "status": out.status,
            "client_msg_id": out.client_msg_id,
            # extras (the brief's four keys stay as they are)
            "chat_id": str(out.chat_id),
            "error": _json(out.error) if out.error else None,
        },
    )


def message_deleted(chat_id: uuid.UUID, message_id: uuid.UUID) -> WsEvent:
    return WsEvent(
        "message.deleted", {"chat_id": str(chat_id), "message_id": str(message_id)}
    )


def chat_updated(row: ChatRow) -> WsEvent:
    return WsEvent("chat.updated", _json(ChatOut.from_models(*row)))


def chat_deleted(chat_id: uuid.UUID) -> WsEvent:
    return WsEvent("chat.deleted", {"chat_id": str(chat_id)})


PONG = WsEvent("pong")

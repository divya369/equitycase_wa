import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from core.time import to_unix_str
from modules.messages.models import Message, MessageStatus

ClientMsgIdStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
# WhatsApp's text body limit
TextBodyStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]
WamidStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]


class TextBody(BaseModel):
    body: str


class MessageContext(BaseModel):
    """The wamid this message replies to."""

    id: str


class ReplyContextIn(BaseModel):
    id: WamidStr


class SendMessageIn(BaseModel):
    # the client's optimistic uuid — the idempotency key
    client_msg_id: ClientMsgIdStr
    # media / templates arrive in P10 / P11
    type: Literal["text"] = "text"
    body: TextBodyStr
    # optional reply, same shape as message.context
    context: ReplyContextIn | None = None


class MessageError(BaseModel):
    code: int | None
    title: str | None


class MessageOut(BaseModel):
    """The Dart `message` model. Build it ONLY via from_model() so REST, the
    webhook and WS frames emit identical JSON."""

    # `from` is a Python keyword; FastAPI serialises by alias
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    chat_id: uuid.UUID
    from_: str = Field(alias="from")
    type: str
    text: TextBody
    # unix seconds as a STRING (Meta's own format)
    timestamp: str
    status: str
    media_url: str | None
    context: MessageContext | None
    client_msg_id: str | None
    # set only when status == failed
    error: MessageError | None

    @classmethod
    def from_model(cls, message: Message) -> MessageOut:
        status = MessageStatus(message.status)
        return cls(
            id=message.id,
            chat_id=message.chat_id,
            from_=message.sender_wa_id,
            type=message.type,
            text=TextBody(body=message.body),
            timestamp=to_unix_str(message.created_at),
            status=status.label,
            media_url=message.media_url,
            context=(
                MessageContext(id=message.reply_to_wamid)
                if message.reply_to_wamid
                else None
            ),
            client_msg_id=message.client_msg_id,
            error=(
                MessageError(code=message.error_code, title=message.error_title)
                if status is MessageStatus.FAILED
                else None
            ),
        )

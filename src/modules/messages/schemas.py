import uuid

from pydantic import BaseModel, ConfigDict, Field

from core.time import to_unix_str
from modules.messages.models import Message, MessageStatus


class TextBody(BaseModel):
    body: str


class MessageContext(BaseModel):
    """The wamid this message replies to."""

    id: str


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

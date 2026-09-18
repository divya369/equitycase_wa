"""Test data helpers — write rows straight to the DB, plus shared asserts."""

from datetime import timedelta

from sqlalchemy import text

from core.database import SessionFactory
from core.time import utcnow
from modules.chats.models import Chat
from modules.contacts.models import Contact
from modules.messages.models import Message, MessageDirection, MessageStatus

USER_KEYS = {"wa_id", "name", "phone", "avatar_url", "about", "is_online", "last_seen"}
MESSAGE_KEYS = {
    "id",
    "chat_id",
    "from",
    "type",
    "text",
    "timestamp",
    "status",
    "media_url",
    "context",
    "client_msg_id",
    "error",
}
CHAT_KEYS = {"id", "contact", "last_message", "unread_count", "is_pinned", "is_muted"}

WA_ID = "919820011223"
BUSINESS_WA_ID = "912240001234"


async def make_contact(wa_id: str = WA_ID, name: str = "Ananya Mehta") -> Contact:
    async with SessionFactory() as session:
        contact = Contact(wa_id=wa_id, name=name, phone=f"+{wa_id}")
        session.add(contact)
        await session.commit()
        return contact


async def make_chat(wa_id: str = WA_ID, **fields) -> Chat:
    await make_contact(wa_id, name=fields.pop("name", "Ananya Mehta"))
    async with SessionFactory() as session:
        chat = Chat(contact_wa_id=wa_id, **fields)
        session.add(chat)
        await session.commit()
        return chat


async def make_open_chat(wa_id: str = WA_ID, **fields) -> Chat:
    """A chat whose customer wrote 1h ago — the 24h window is open."""
    return await make_chat(
        wa_id, last_inbound_at=utcnow() - timedelta(hours=1), **fields
    )


async def make_messages(chat: Chat, count: int) -> list[Message]:
    """`count` inbound messages 1 minute apart, oldest first; the newest
    becomes the chat's last message."""
    base = utcnow() - timedelta(hours=1)
    async with SessionFactory() as session:
        messages = [
            Message(
                chat_id=chat.id,
                sender_wa_id=chat.contact_wa_id,
                direction=MessageDirection.IN,
                body=f"msg {i}",
                status=MessageStatus.DELIVERED,
                wamid=f"wamid.{chat.id}.{i}",
                created_at=base + timedelta(minutes=i),
            )
            for i in range(count)
        ]
        session.add_all(messages)
        await session.flush()
        chat.last_message_id = messages[-1].id
        session.add(chat)
        await session.commit()
        return messages


async def make_outbound(chat: Chat, **fields) -> Message:
    async with SessionFactory() as session:
        message = Message(
            chat_id=chat.id,
            sender_wa_id=BUSINESS_WA_ID,
            direction=MessageDirection.OUT,
            body=fields.pop("body", "hello"),
            **fields,
        )
        session.add(message)
        await session.commit()
        return message


async def get_message(message_id) -> Message:
    async with SessionFactory() as session:
        return await session.get(Message, message_id)


async def count(table: str) -> int:
    async with SessionFactory() as session:
        return (await session.exec(text(f"SELECT count(*) FROM {table}"))).one()[0]


def assert_error(resp, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    assert set(resp.json()) == {"errors"}
    assert resp.json()["errors"]["code"] == code

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_unix_str(value: datetime) -> str:
    """Meta's timestamp format: unix seconds as a string."""
    return str(int(value.timestamp()))

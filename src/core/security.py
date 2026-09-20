import asyncio
import hmac
import secrets
import uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from config.app_config import app_config
from core.time import utcnow

JWT_ALGORITHM = "HS256"
# sub = "operator:<id>". Tokens issued before P12 carry the bare subject and
# mean the seeded operator, so phones already logged in keep working.
OPERATOR_SUBJECT = "operator"
SEEDED_OPERATOR_ID = 1

_hasher = PasswordHasher()


class InvalidTokenError(Exception):
    pass


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token(operator_id: int = SEEDED_OPERATOR_ID) -> str:
    now = utcnow()
    payload = {
        "sub": f"{OPERATOR_SUBJECT}:{operator_id}",
        "iat": now,
        "exp": now + timedelta(hours=app_config.jwt_ttl_hours),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(
        payload,
        app_config.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            app_config.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.PyJWTError as e:
        raise InvalidTokenError(type(e).__name__) from e

    payload["operator_id"] = _operator_id_from_subject(payload.get("sub"))
    return payload


def _operator_id_from_subject(subject: object) -> int:
    """ "operator:<id>", or the pre-P12 "operator" (= the seeded operator)."""
    if subject == OPERATOR_SUBJECT:
        return SEEDED_OPERATOR_ID
    if not isinstance(subject, str) or not subject.startswith(f"{OPERATOR_SUBJECT}:"):
        raise InvalidTokenError("wrong subject")
    try:
        return int(subject.split(":", 1)[1])
    except ValueError as e:
        raise InvalidTokenError("wrong subject") from e


# ---------------------------------------------------------------------------
# OTP
# ---------------------------------------------------------------------------
def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def hash_otp(code: str) -> str:
    # argon2 is deliberately CPU-heavy — keep it off the event loop
    return await asyncio.to_thread(_hasher.hash, code)


async def verify_otp_hash(code_hash: str, code: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(code_hash, code)
        except VerificationError, InvalidHashError:
            return False

    return await asyncio.to_thread(_verify)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())

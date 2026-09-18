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
OPERATOR_SUBJECT = "operator"

_hasher = PasswordHasher()


class InvalidTokenError(Exception):
    pass


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token() -> str:
    now = utcnow()
    payload = {
        "sub": OPERATOR_SUBJECT,
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

    if payload.get("sub") != OPERATOR_SUBJECT:
        raise InvalidTokenError("wrong subject")

    return payload


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

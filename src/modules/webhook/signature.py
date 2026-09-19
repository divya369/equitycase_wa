import hashlib
import hmac

from config.app_config import app_config


def compute_signature(body: bytes) -> str:
    """Meta's X-Hub-Signature-256 value for a raw request body."""
    secret = app_config.meta_app_secret.get_secret_value().encode()
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def is_valid_signature(body: bytes, header: str | None) -> bool:
    """Verify on the RAW bytes, in constant time."""
    if not header:
        return False
    return hmac.compare_digest(compute_signature(body), header)

from typing import Any


def error_response(
    *,
    code: str,
    message: str,
    request_id: str,
    details: Any | None = None,
) -> dict:
    error = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }

    if details is not None:
        error["details"] = details

    return {"errors": error}

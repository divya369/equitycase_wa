from typing import Any


def error_response(
    *,
    code: str,
    message: str,
    details: Any | None = None,
) -> dict:
    response = {
        "errors": {
            "code": code,
            "message": message,
        }
    }

    if details is not None:
        response["errors"]["details"] = details

    return response

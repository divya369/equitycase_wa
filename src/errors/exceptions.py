from typing import Any

from errors.codes import ErrorCode


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: Any | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details

        super().__init__(message)


class NotFoundError(AppError):
    def __init__(
        self,
        message: str = "Resource not found",
        details: Any | None = None,
    ):
        super().__init__(
            code=ErrorCode.NOT_FOUND,
            message=message,
            status_code=404,
            details=details,
        )


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(
            code=ErrorCode.UNAUTHORIZED,
            message=message,
            status_code=401,
        )


class ConflictError(AppError):
    def __init__(self, message: str = "Resource already exists"):
        super().__init__(
            code=ErrorCode.CONFLICT,
            message=message,
            status_code=409,
        )

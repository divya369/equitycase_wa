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


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden"):
        super().__init__(
            code=ErrorCode.FORBIDDEN,
            message=message,
            status_code=403,
        )


class ConflictError(AppError):
    def __init__(self, message: str = "Resource already exists"):
        super().__init__(
            code=ErrorCode.CONFLICT,
            message=message,
            status_code=409,
        )


class ConversationWindowClosedError(AppError):
    def __init__(
        self,
        message: str = (
            "The 24-hour conversation window is closed. "
            "Only approved templates can be sent."
        ),
    ):
        super().__init__(
            code=ErrorCode.CONVERSATION_WINDOW_CLOSED,
            message=message,
            status_code=409,
        )


class InvalidOtpError(AppError):
    def __init__(self, message: str = "Invalid or expired code"):
        super().__init__(
            code=ErrorCode.INVALID_OTP,
            message=message,
            status_code=401,
        )


class RateLimitedError(AppError):
    def __init__(self, message: str = "Too many requests"):
        super().__init__(
            code=ErrorCode.RATE_LIMITED,
            message=message,
            status_code=429,
        )


class UpstreamError(AppError):
    def __init__(
        self,
        message: str = "Upstream service error",
        details: Any | None = None,
    ):
        super().__init__(
            code=ErrorCode.BAD_GATEWAY,
            message=message,
            status_code=502,
            details=details,
        )

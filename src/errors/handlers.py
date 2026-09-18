import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from errors.codes import ErrorCode
from errors.exceptions import AppError
from errors.responses import error_response

logger = structlog.get_logger()


def get_request_id(request: Request) -> str:
    return request.state.request_id


async def app_error_handler(
    request: Request,
    exc: AppError,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            code=exc.code,
            message=exc.message,
            request_id=get_request_id(request),
            details=exc.details,
        ),
    )


async def http_error_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content=error_response(
                code=ErrorCode.NOT_FOUND,
                message="Route not found",
                request_id=get_request_id(request),
            ),
        )

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            code=f"http_{exc.status_code}",
            message=str(exc.detail),
            request_id=get_request_id(request),
        ),
    )


async def rate_limit_error_handler(
    request: Request,
    exc: RateLimitExceeded,
) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content=error_response(
            code=ErrorCode.RATE_LIMITED,
            message="Too many requests. Try again later.",
            request_id=get_request_id(request),
            details={"limit": str(exc.detail)},
        ),
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            request_id=get_request_id(request),
            details=exc.errors(),
        ),
    )


async def unhandled_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        method=request.method,
        path=request.url.path,
    )

    return JSONResponse(
        status_code=500,
        content=error_response(
            code=ErrorCode.INTERNAL_ERROR,
            request_id=get_request_id(request),
            message="Internal server error",
        ),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        AppError,
        app_error_handler,
    )

    app.add_exception_handler(
        RateLimitExceeded,
        rate_limit_error_handler,
    )

    app.add_exception_handler(
        StarletteHTTPException,
        http_error_handler,
    )

    app.add_exception_handler(
        RequestValidationError,
        validation_error_handler,
    )

    app.add_exception_handler(
        Exception,
        unhandled_error_handler,
    )

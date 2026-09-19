import logging
import re
import sys

import structlog

_TOKEN_QUERY = re.compile(r"(token=)[^&\s\"']+", re.IGNORECASE)


class RedactTokenQueryFilter(logging.Filter):
    """Strip ?token=<jwt> from log lines (uvicorn access + websocket logs)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _TOKEN_QUERY.sub(r"\1***", a) if isinstance(a, str) else a
                for a in record.args
            )
        if isinstance(record.msg, str):
            record.msg = _TOKEN_QUERY.sub(r"\1***", record.msg)
        return True


def configure_logging() -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            timestamper,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            timestamper,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RedactTokenQueryFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True

    # httpx logs every request URL at INFO — the SMS URL carries the API key
    # and the OTP code
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

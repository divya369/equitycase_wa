from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

logger = structlog.get_logger("lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("application_starting")

    yield

    logger.info("application_stopping")
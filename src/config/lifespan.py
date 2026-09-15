from contextlib import asynccontextmanager
from fastapi import FastAPI
from config.app_config import app_config

import structlog

logger = structlog.get_logger("lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info(f"application_starting")

    yield

    logger.info("application_stopping")
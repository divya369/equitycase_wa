from contextlib import asynccontextmanager
from fastapi import FastAPI
from config.app_config import app_config


@asynccontextmanager
async def lifespan(app: FastAPI):

    print(f"Starting {app_config.app_name} on port {app_config.app_port}...")

    yield

    print("Shutting down...")
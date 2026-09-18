from fastapi import APIRouter, FastAPI

from modules.health.router import router as health_router

# Every /v1 router is added here; each one depends on the operator JWT.
v1_router = APIRouter(prefix="/v1")


def register_routes(app: FastAPI) -> None:
    app.include_router(health_router)
    app.include_router(v1_router)

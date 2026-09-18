from fastapi import APIRouter, Depends, FastAPI

from modules.auth.dependencies import get_current_operator
from modules.auth.router import router as auth_router
from modules.health.router import router as health_router
from modules.operator.router import router as me_router

# /v1/auth/* — public (OTP login)
v1_router = APIRouter(prefix="/v1")
v1_router.include_router(auth_router)

# Every other /v1 router goes here: the operator JWT is enforced ONCE, for all.
protected_router = APIRouter(dependencies=[Depends(get_current_operator)])
protected_router.include_router(me_router)

v1_router.include_router(protected_router)


def register_routes(app: FastAPI) -> None:
    app.include_router(health_router)
    app.include_router(v1_router)

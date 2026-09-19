from fastapi import APIRouter, Depends, FastAPI

from modules.auth.dependencies import get_current_operator
from modules.auth.router import router as auth_router
from modules.chats.router import router as chats_router
from modules.contacts.router import router as contacts_router
from modules.health.router import router as health_router
from modules.messages.router import router as messages_router
from modules.operator.router import router as me_router
from modules.webhook.router import router as webhook_router

# /v1/auth/* — public (OTP login)
v1_router = APIRouter(prefix="/v1")
v1_router.include_router(auth_router)

# Every other /v1 router goes here: the operator JWT is enforced ONCE, for all.
protected_router = APIRouter(dependencies=[Depends(get_current_operator)])
protected_router.include_router(me_router)
protected_router.include_router(chats_router)
protected_router.include_router(messages_router)
protected_router.include_router(contacts_router)

v1_router.include_router(protected_router)


def register_routes(app: FastAPI) -> None:
    app.include_router(health_router)
    # Meta webhook: signature-verified, no JWT, no envelope
    app.include_router(webhook_router)
    app.include_router(v1_router)

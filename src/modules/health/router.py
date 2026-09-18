from fastapi import APIRouter

from modules.health.schemas import HealthOut
from modules.health.service import HealthService

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthOut)
async def healthz() -> HealthOut:
    await HealthService().check()
    return HealthOut(ok=True)

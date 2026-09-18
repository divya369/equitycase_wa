from fastapi import APIRouter

from core.responses import ApiResponse, MetaDep
from modules.health.schemas import HealthOut
from modules.health.service import HealthService

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=ApiResponse[HealthOut])
async def healthz(meta: MetaDep) -> ApiResponse[HealthOut]:
    await HealthService().check()
    return ApiResponse(data=HealthOut(ok=True), meta=meta)

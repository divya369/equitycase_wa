"""Marketing opt-outs. Not the operator app: these routes are for the blast
CLI and are guarded by the shared `X-API-Key`, not the operator JWT.
"""

from fastapi import APIRouter, Response, status

from core.phone import PhoneStr, to_wa_id
from core.responses import ApiResponse, MetaDep
from modules.marketing.dependencies import MarketingApiKey, MarketingServiceDep
from modules.marketing.schemas import OptOutStatusOut
from modules.marketing.service import SOURCE_MANUAL

router = APIRouter(
    prefix="/marketing",
    tags=["marketing"],
    dependencies=[MarketingApiKey],
)


@router.get("/number/{phone}", response_model=ApiResponse[OptOutStatusOut])
async def opt_out_status(
    phone: PhoneStr, service: MarketingServiceDep, meta: MetaDep
) -> ApiResponse[OptOutStatusOut]:
    """`opted_out: true` -> do NOT send this number a marketing message."""
    wa_id = to_wa_id(phone)
    row = await service.status(wa_id)
    return ApiResponse(data=OptOutStatusOut.from_model(wa_id, row), meta=meta)


@router.get("/opt-outs", response_model=ApiResponse[list[OptOutStatusOut]])
async def list_opt_outs(
    service: MarketingServiceDep, meta: MetaDep
) -> ApiResponse[list[OptOutStatusOut]]:
    rows = await service.list_opt_outs()
    return ApiResponse(
        data=[OptOutStatusOut.from_model(row.wa_id, row) for row in rows], meta=meta
    )


@router.post("/number/{phone}/opt-out", status_code=status.HTTP_204_NO_CONTENT)
async def add_opt_out(phone: PhoneStr, service: MarketingServiceDep) -> Response:
    """Manual entry (someone asked by phone or email). Safe to repeat."""
    await service.opt_out(to_wa_id(phone), source=SOURCE_MANUAL)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/number/{phone}/opt-out", status_code=status.HTTP_204_NO_CONTENT)
async def remove_opt_out(phone: PhoneStr, service: MarketingServiceDep) -> Response:
    """Only on the customer's explicit opt-in."""
    await service.opt_in(to_wa_id(phone))
    return Response(status_code=status.HTTP_204_NO_CONTENT)

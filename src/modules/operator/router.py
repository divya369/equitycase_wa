from fastapi import APIRouter, Response, status

from core.responses import ApiResponse, MetaDep
from modules.auth.dependencies import CurrentOperator
from modules.contacts.schemas import UserOut
from modules.operator.dependencies import OperatorServiceDep
from modules.operator.schemas import FcmTokenDeleteIn, FcmTokenIn, UpdateMeIn

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=ApiResponse[UserOut])
async def get_me(operator: CurrentOperator, meta: MetaDep) -> ApiResponse[UserOut]:
    return ApiResponse(data=UserOut.from_operator(operator), meta=meta)


@router.patch("", response_model=ApiResponse[UserOut])
async def update_me(
    body: UpdateMeIn,
    operator: CurrentOperator,
    service: OperatorServiceDep,
    meta: MetaDep,
) -> ApiResponse[UserOut]:
    operator = await service.update_name(operator, body.name)
    return ApiResponse(data=UserOut.from_operator(operator), meta=meta)


@router.post("/fcm-token", status_code=status.HTTP_204_NO_CONTENT)
async def register_fcm_token(
    body: FcmTokenIn, operator: CurrentOperator, service: OperatorServiceDep
) -> Response:
    await service.register_fcm_token(
        token=body.token, platform=body.platform, operator_id=operator.id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/fcm-token", status_code=status.HTTP_204_NO_CONTENT)
async def remove_fcm_token(
    body: FcmTokenDeleteIn, service: OperatorServiceDep
) -> Response:
    await service.remove_fcm_token(body.token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

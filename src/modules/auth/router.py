from fastapi import APIRouter, Request, Response, status

from core.rate_limit import OTP_RATE_LIMIT, limiter
from core.responses import ApiResponse, MetaDep
from modules.auth.dependencies import AuthServiceDep
from modules.auth.schemas import AuthOut, OtpRequestIn, OtpVerifyIn
from modules.contacts.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/request", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(OTP_RATE_LIMIT)
async def request_otp(
    request: Request,
    body: OtpRequestIn,
    service: AuthServiceDep,
) -> Response:
    await service.request_otp(body.phone)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/otp/verify", response_model=ApiResponse[AuthOut])
@limiter.limit(OTP_RATE_LIMIT)
async def verify_otp(
    request: Request,
    body: OtpVerifyIn,
    service: AuthServiceDep,
    meta: MetaDep,
) -> ApiResponse[AuthOut]:
    token, operator = await service.verify_otp(phone=body.phone, code=body.code)
    return ApiResponse(
        data=AuthOut(token=token, user=UserOut.from_operator(operator)),
        meta=meta,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    """Stateless JWT: the client drops its token (and should DELETE
    /v1/me/fcm-token first so the device stops receiving pushes)."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)

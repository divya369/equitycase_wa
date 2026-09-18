from fastapi import APIRouter, Response, status

from core.responses import ApiResponse, MetaDep
from modules.contacts.dependencies import ContactServiceDep
from modules.contacts.schemas import CreateContactIn, UserOut

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=ApiResponse[list[UserOut]])
async def list_contacts(
    service: ContactServiceDep, meta: MetaDep
) -> ApiResponse[list[UserOut]]:
    contacts = await service.list_contacts()
    return ApiResponse(data=[UserOut.from_contact(c) for c in contacts], meta=meta)


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=ApiResponse[UserOut]
)
async def create_contact(
    body: CreateContactIn, service: ContactServiceDep, meta: MetaDep
) -> ApiResponse[UserOut]:
    contact = await service.create_contact(name=body.name, phone=body.phone)
    return ApiResponse(data=UserOut.from_contact(contact), meta=meta)


@router.delete("/{wa_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(wa_id: str, service: ContactServiceDep) -> Response:
    await service.delete_contact(wa_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

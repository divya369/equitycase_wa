from typing import Annotated

from fastapi import Depends

from core.database import SessionDep
from modules.contacts.repository import ContactRepository
from modules.contacts.service import ContactService


def get_contact_service(session: SessionDep) -> ContactService:
    return ContactService(session=session, contacts=ContactRepository(session))


ContactServiceDep = Annotated[ContactService, Depends(get_contact_service)]

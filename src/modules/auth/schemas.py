from typing import Annotated

from pydantic import BaseModel, StringConstraints

from core.phone import PhoneStr
from modules.contacts.schemas import UserOut

OtpCodeStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\d{4,8}$"),
]


class OtpRequestIn(BaseModel):
    phone: PhoneStr


class OtpVerifyIn(BaseModel):
    phone: PhoneStr
    code: OtpCodeStr


class AuthOut(BaseModel):
    token: str
    user: UserOut

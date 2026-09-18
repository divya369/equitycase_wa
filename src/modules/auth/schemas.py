from typing import Annotated

from pydantic import BaseModel, StringConstraints

from modules.contacts.schemas import UserOut

# Lenient on formatting (+, spaces, dashes); the service compares digits only
PhoneStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\+?[\d\s\-()]{8,20}$"),
]
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

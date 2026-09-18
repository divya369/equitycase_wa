from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

NameStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
FcmTokenStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]


class UpdateMeIn(BaseModel):
    name: NameStr


class FcmTokenIn(BaseModel):
    token: FcmTokenStr
    platform: Literal["android", "ios"]


class FcmTokenDeleteIn(BaseModel):
    token: FcmTokenStr

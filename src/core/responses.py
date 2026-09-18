"""Standard SUCCESS envelope — the counterpart of errors/responses.py.

    success: {"data": <payload>, "meta": {"request_id": "..."}}
    error:   {"errors": {"code": "...", "message": "...", "request_id": "...", "details"?: ...}}

Every JSON route returns ApiResponse[T]. 204 responses have no body.
"""

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel


class ResponseMeta(BaseModel):
    request_id: str


class ApiResponse[T](BaseModel):
    data: T
    meta: ResponseMeta


def get_response_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(request_id=request.state.request_id)


MetaDep = Annotated[ResponseMeta, Depends(get_response_meta)]

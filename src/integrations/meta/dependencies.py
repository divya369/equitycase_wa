from typing import Annotated

from fastapi import Depends, Request

from integrations.meta.client import MetaClient


def get_meta_client(request: Request) -> MetaClient:
    """The shared client created in lifespan (tests override this)."""
    return request.app.state.meta


MetaClientDep = Annotated[MetaClient, Depends(get_meta_client)]

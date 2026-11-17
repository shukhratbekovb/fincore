from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from backend.application.share.dtos.client_info import ClientInfo


def get_client_info(request: Request) -> ClientInfo:
    if request.client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot determine client IP",
        )

    # Uvicorn resolves forwarded headers only when the peer is a trusted proxy.
    return ClientInfo(
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent"),
    )


ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.presentation.api.v1.dependencies.auth import TokenIssuerDep
from backend.presentation.api.v1.dependencies.user import CurrentUserQueryDep


BearerDep = Annotated[
    HTTPAuthorizationCredentials,
    Depends(HTTPBearer()),
]


def get_current_user_id(
        credentials: BearerDep,
        token_issuer: TokenIssuerDep,
) -> UUID:
    return token_issuer.decode(credentials.credentials)


CurrentUserIdDep = Annotated[UUID, Depends(get_current_user_id)]


async def get_current_active_user_id(
        current_user_id: CurrentUserIdDep,
        query: CurrentUserQueryDep,
) -> UUID:
    await query.execute(user_id=current_user_id)
    return current_user_id


CurrentActiveUserIdDep = Annotated[UUID, Depends(get_current_active_user_id)]

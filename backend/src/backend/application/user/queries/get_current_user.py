from dataclasses import dataclass
from uuid import UUID

from backend.application.auth.errors import UserInactiveError
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.dtos.base import UserDTO
from backend.application.user.errors import UserNotFoundError


@dataclass(frozen=True)
class GetCurrentUserQuery:
    uow: IUnitOfWork

    async def execute(
            self,
            user_id: UUID
    ) -> UserDTO:
        async with self.uow:
            user = await self.uow.users.get_by_id(user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            return UserDTO(
                id=user.id,
                username=user.username,
                email=user.email,
                created_at=user.created_at
            )

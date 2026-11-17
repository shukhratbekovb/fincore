from dataclasses import dataclass
from uuid import UUID

from backend.application.auth.errors import UserInactiveError
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError


@dataclass(frozen=True)
class RemoveAllSessionsUseCase:
    uow: IUnitOfWork
    clock: IClock

    async def execute(
            self,
            user_id: UUID
    ) -> None:
        async with self.uow:
            user = await self.uow.users.get_by_id_for_update(user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()
            now = self.clock.now()
            await self.uow.sessions.revoke_all_by_user_id(user.id, now=now)
            await self.uow.commit()

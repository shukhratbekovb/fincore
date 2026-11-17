from dataclasses import dataclass

from backend.application.auth.errors import UserInactiveError
from backend.application.session.dtos.remove_session import RemoveSessionCommand
from backend.application.session.errors import SessionNotFoundError
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError


@dataclass(frozen=True)
class RemoveSessionUseCase:
    uow: IUnitOfWork
    clock: IClock

    async def execute(
            self,
            cmd: RemoveSessionCommand
    ) -> None:
        async with self.uow:
            user = await self.uow.users.get_by_id_for_update(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            session = await self.uow.sessions.get_by_id_for_update(cmd.session_id)

            if session is None or session.user_id != user.id:
                raise SessionNotFoundError()

            if session.revoked_at is not None:
                return

            session.revoke(now=self.clock.now())

            await self.uow.sessions.save(session)

            await self.uow.commit()

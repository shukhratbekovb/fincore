from dataclasses import dataclass
from uuid import UUID

from backend.application.auth.errors import UserInactiveError
from backend.application.session.dtos.base import SessionDTO
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError


@dataclass(frozen=True)
class GetUserActiveSessionsQuery:
    uow: IUnitOfWork
    clock: IClock

    async def execute(
            self,
            user_id: UUID
    ) -> list[SessionDTO]:
        async with self.uow:
            user = await self.uow.users.get_by_id(user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()
            now = self.clock.now()

            sessions = await self.uow.sessions.get_active_by_user_id(user_id, now=now)

        return [
            SessionDTO(
                id=session.id,
                expires_at=session.expires_at,
                ip_address=session.ip_address,
                last_ip_address=session.last_ip_address,
                last_user_agent=session.last_user_agent,
                user_agent=session.user_agent,
                last_used_at=session.last_used_at,
                created_at=session.created_at
            )
            for session in sessions
        ]

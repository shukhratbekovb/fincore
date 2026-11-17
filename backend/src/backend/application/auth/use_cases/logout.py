from dataclasses import dataclass

from backend.application.auth.dtos.logout import LogoutUserCommand
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.verification.interfaces.token_hasher import ITokenHasher


@dataclass(frozen=True)
class LogoutUserUseCase:
    uow: IUnitOfWork
    token_hasher: ITokenHasher
    clock: IClock

    async def execute(self, cmd: LogoutUserCommand) -> None:
        async with self.uow:
            token = await self.uow.refresh_tokens.get_by_token_hash(
                self.token_hasher.hash(cmd.refresh_token)
            )
            if token is None:
                return
            session = await self.uow.sessions.get_by_id_for_update(token.session_id)
            if session is None or session.revoked_at is not None:
                return
            # Even an old rotated token can log out its owning session.
            session.revoke(now=self.clock.now())
            await self.uow.sessions.save(session)
            await self.uow.commit()

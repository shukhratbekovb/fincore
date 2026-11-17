from dataclasses import dataclass

from backend.application.auth.dtos.change_password import ChangePasswordCommand
from backend.application.auth.errors import InvalidCredentialsError, UserInactiveError
from backend.application.auth.interfaces.password_hasher import IPasswordHasher
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork


@dataclass(frozen=True)
class ChangePasswordUseCase:
    uow: IUnitOfWork
    password_hasher: IPasswordHasher
    clock: IClock

    async def execute(self, cmd: ChangePasswordCommand) -> None:
        async with self.uow:
            user = await self.uow.users.get_by_id_for_update(cmd.user_id)
            if user is None or user.password_hash is None:
                raise InvalidCredentialsError()
            if not self.password_hasher.verify(cmd.current_password, user.password_hash):
                raise InvalidCredentialsError()
            if not user.is_active():
                raise UserInactiveError()

            user.change_password(self.password_hasher.hash(cmd.new_password))
            await self.uow.users.save(user)
            await self.uow.sessions.revoke_all_by_user_id(
                user.id, now=self.clock.now(),
            )
            await self.uow.commit()

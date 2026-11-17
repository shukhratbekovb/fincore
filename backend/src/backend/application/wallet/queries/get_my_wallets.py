from dataclasses import dataclass

from backend.application.auth.errors import UserInactiveError
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.base import WalletDTO
from backend.application.wallet.dtos.get_my_wallets import GetMyWalletsCommand


@dataclass(frozen=True)
class GetMyWalletsQuery:
    uow: IUnitOfWork

    async def execute(
            self,
            cmd: GetMyWalletsCommand
    ) -> list[WalletDTO]:
        async with self.uow:
            user = await self.uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            wallets = await self.uow.wallet_reader.list_by_user_id(
                user_id=user.id,
                filters=cmd.filters
            )

            return wallets

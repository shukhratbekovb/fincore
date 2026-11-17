from dataclasses import dataclass

from backend.application.auth.errors import UserInactiveError
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.base import WalletDTO
from backend.application.wallet.dtos.get_wallet import GetWalletCommand
from backend.application.wallet.errors import WalletNotFoundError


@dataclass(frozen=True)
class GetWalletQuery:
    uow: IUnitOfWork

    async def execute(
            self,
            cmd: GetWalletCommand
    ) -> WalletDTO:
        async with self.uow:
            user = await self.uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            wallet = await self.uow.wallet_reader.get_by_id_for_user(
                cmd.wallet_id,
                user_id=user.id
            )
            if wallet is None or wallet.user_id != user.id:
                raise WalletNotFoundError()

            return wallet

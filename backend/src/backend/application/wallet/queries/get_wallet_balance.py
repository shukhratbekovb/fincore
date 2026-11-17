from dataclasses import dataclass
from uuid import UUID

from backend.application.auth.errors import UserInactiveError
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.get_wallet_balance import GetWalletBalanceCommand
from backend.application.wallet.errors import WalletNotFoundError
from backend.application.wallet_balance.dtos.base import WalletBalanceDTO


@dataclass(frozen=True)
class GetWalletBalanceQuery:
    uow: IUnitOfWork

    async def execute(
            self,
            cmd: GetWalletBalanceCommand
    ) -> WalletBalanceDTO:
        if not isinstance(cmd.user_id, UUID) or not isinstance(cmd.wallet_id, UUID):
            raise TypeError("User and wallet IDs must be UUIDs")

        async with self.uow:
            user = await self.uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            balance = await self.uow.wallet_balance_reader.get_by_wallet_id_for_user(
                cmd.wallet_id,
                user_id=user.id,
            )
            if balance is None or balance.wallet_id != cmd.wallet_id:
                raise WalletNotFoundError()

            return balance

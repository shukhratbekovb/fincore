from dataclasses import dataclass

from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.wallet.dtos.rename_wallet import RenameWalletCommand
from backend.application.wallet.errors import WalletNotFoundError


@dataclass(frozen=True)
class RenameWalletUseCase:
    uow: IUnitOfWork

    async def execute(self, cmd: RenameWalletCommand) -> None:
        async with self.uow:
            wallet = await self.uow.wallets.get_by_id_for_update(cmd.wallet_id)
            if wallet is None or wallet.user_id != cmd.user_id:
                raise WalletNotFoundError()

            wallet.change_name(cmd.name)
            await self.uow.wallets.save(wallet)
            await self.uow.commit()

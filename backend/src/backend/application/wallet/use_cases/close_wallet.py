from dataclasses import dataclass

from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.wallet.dtos.close_wallet import CloseWalletCommand
from backend.application.wallet.errors import (
    WalletAccountingStateError,
    WalletBalanceNotZeroError,
    WalletNotFoundError,
)
from backend.domain.ledger_account.enums import AccountType


@dataclass(frozen=True)
class CloseWalletUseCase:
    uow: IUnitOfWork

    async def execute(self, cmd: CloseWalletCommand) -> None:
        async with self.uow:
            # Posting must follow this same order and recheck statuses under lock.
            wallet = await self.uow.wallets.get_by_id_for_update(cmd.wallet_id)
            if wallet is None or wallet.user_id != cmd.user_id:
                raise WalletNotFoundError()
            balance = await self.uow.wallet_balances.get_by_wallet_id_for_update(wallet.id)
            if balance is None or balance.wallet_id != wallet.id:
                raise WalletAccountingStateError()
            account = await self.uow.ledger_accounts.get_by_wallet_id_for_update(wallet.id)
            if (
                account is None
                or account.wallet_id != wallet.id
                or account.currency != wallet.currency
                or account.account_type != AccountType.LIABILITY
            ):
                raise WalletAccountingStateError()
            if balance.posted_minor != 0:
                raise WalletBalanceNotZeroError()

            wallet.close()
            account.close()
            await self.uow.wallets.save(wallet)
            await self.uow.ledger_accounts.save(account)
            await self.uow.commit()

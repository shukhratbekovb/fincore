from dataclasses import dataclass

from backend.application.auth.errors import UserInactiveError
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.freeze_wallet import FreezeWalletCommand
from backend.application.wallet.errors import WalletAccountingStateError, WalletNotFoundError
from backend.domain.ledger_account.enums import AccountStatus, AccountType
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.errors import WalletClosedError


@dataclass(frozen=True)
class FreezeWalletUseCase:
    """Allow an active owner to freeze their wallet without changing money."""

    uow: IUnitOfWork

    async def execute(self, cmd: FreezeWalletCommand) -> None:
        async with self.uow:
            user = await self.uow.users.get_by_id_for_update(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            # Match the posting/closure lock order; status is checked under lock.
            wallet = await self.uow.wallets.get_by_id_for_update(cmd.wallet_id)
            if wallet is None or wallet.user_id != cmd.user_id:
                raise WalletNotFoundError()
            if wallet.status == WalletStatusEnum.CLOSED:
                raise WalletClosedError()

            balance = await self.uow.wallet_balances.get_by_wallet_id_for_update(wallet.id)
            if balance is None or balance.wallet_id != wallet.id:
                raise WalletAccountingStateError()
            account = await self.uow.ledger_accounts.get_by_wallet_id_for_update(wallet.id)
            if (
                account is None
                or account.wallet_id != wallet.id
                or account.currency != wallet.currency
                or account.account_type != AccountType.LIABILITY
                or account.status != AccountStatus.ACTIVE
            ):
                raise WalletAccountingStateError()

            # Repeated requests succeed without touching timestamps or balances.
            if wallet.status == WalletStatusEnum.FROZEN:
                return

            wallet.freeze()
            await self.uow.wallets.save(wallet)
            await self.uow.commit()

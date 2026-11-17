from dataclasses import dataclass

from backend.application.auth.errors import UserInactiveError
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.share.interfaces.clock import IClock
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.create_wallet import CreateWalletCommand, CreateWalletResult
from backend.application.wallet.errors import WalletNumberAlreadyExistsError
from backend.application.wallet.interfaces.wallet_number_generator import WalletNumberGenerator
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet_balance.entities import WalletBalance
from backend.domain.ledger_account.entities import LedgerAccount


@dataclass(frozen=True)
class CreateWalletUseCase:
    uow: IUnitOfWork
    number_generator: WalletNumberGenerator
    clock: IClock
    max_number_attempts: int = 3

    def __post_init__(self) -> None:
        if self.max_number_attempts < 1:
            raise ValueError("Number generation attempts must be positive")

    async def execute(
            self,
            cmd: CreateWalletCommand
    ) -> CreateWalletResult:
        for _ in range(self.max_number_attempts - 1):
            try:
                return await self._create(cmd)
            except WalletNumberAlreadyExistsError:
                # __aexit__ must finish rollback before a fresh attempt starts.
                continue

        return await self._create(cmd)

    async def _create(self, cmd: CreateWalletCommand) -> CreateWalletResult:
        async with self.uow:
            user = await self.uow.users.get_by_id_for_update(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()
            number = self.number_generator.generate()
            now = self.clock.now()

            wallet = Wallet.create(
                user_id=user.id,
                number=number,
                name=cmd.name,
                currency=cmd.currency
            )

            balance = WalletBalance.create(wallet_id=wallet.id, now=now)
            account = LedgerAccount.for_wallet(
                wallet_id=wallet.id, currency=wallet.currency, now=now,
            )

            await self.uow.wallets.add(wallet)
            await self.uow.wallet_balances.add(balance)
            await self.uow.ledger_accounts.add(account)
            await self.uow.commit()

        return CreateWalletResult(
            wallet_id=wallet.id
        )

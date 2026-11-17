from typing import Protocol, Self

from backend.application.session.interfaces.repository import ISessionRepository, IRefreshTokenRepository
from backend.application.transfer.interfaces.repository import ITransferRepository
from backend.application.transfer.interfaces.reader import ITransferReader
from backend.application.user.interfaces.repository import IUserRepository
from backend.application.share.interfaces.outbox import IOutbox
from backend.application.verification.interfaces.repository import IVerificationChallengeRepository
from backend.application.wallet.interfaces.reader import IWalletReader
from backend.application.wallet.interfaces.repository import IWalletRepository
from backend.application.wallet_balance.interfaces.repository import IWalletBalanceRepository
from backend.application.ledger_account.interfaces.repository import ILedgerAccountRepository
from backend.application.ledger_transaction.interfaces.repository import ILedgerTransactionRepository
from backend.application.idempotency.interfaces.repository import IIdempotencyRepository
from backend.application.sandbox_top_up.interfaces.repository import ISandboxTopUpRepository
from backend.application.sandbox_top_up.interfaces.operator import ISandboxOperatorReader
from backend.application.history.interfaces.reader import ITransactionHistoryReader
from backend.application.wallet_balance.interfaces.reader import IWalletBalanceReader


class IUnitOfWork(Protocol):
    """Repositories and outbox share one transaction; roll back on failure.

    User storage must enforce email/username uniqueness and translate conflicts
    into the corresponding application errors, including concurrent inserts.

    Each entry starts a fresh transaction. Exit rolls back uncommitted work and
    discards transaction-local entities, including after a failed commit, so the
    UoW can be re-entered safely for an explicit application retry.
    """

    @property
    def users(self) -> IUserRepository: ...

    @property
    def refresh_tokens(self) -> IRefreshTokenRepository: ...

    @property
    def sessions(self) -> ISessionRepository: ...

    @property
    def verification_challenges(self) -> IVerificationChallengeRepository: ...

    @property
    def wallets(self) -> IWalletRepository: ...

    @property
    def wallet_balances(self) -> IWalletBalanceRepository: ...

    @property
    def ledger_accounts(self) -> ILedgerAccountRepository: ...

    @property
    def transfers(self) -> ITransferRepository: ...

    @property
    def ledger_transactions(self) -> ILedgerTransactionRepository: ...

    @property
    def idempotency(self) -> IIdempotencyRepository: ...

    @property
    def sandbox_top_ups(self) -> ISandboxTopUpRepository: ...

    @property
    def sandbox_operator_reader(self) -> ISandboxOperatorReader: ...

    @property
    def outbox(self) -> IOutbox: ...

    @property
    def wallet_reader(self) -> IWalletReader: ...

    @property
    def transfer_reader(self) -> ITransferReader: ...

    @property
    def transaction_history_reader(self) -> ITransactionHistoryReader: ...

    @property
    def wallet_balance_reader(self) -> IWalletBalanceReader: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

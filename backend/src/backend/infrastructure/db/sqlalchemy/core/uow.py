from dataclasses import dataclass
from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.auth.errors import EmailAlreadyExistError, UsernameAlreadyExistError
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.wallet.errors import WalletNumberAlreadyExistsError

from backend.infrastructure.db.sqlalchemy.repository.user import SqlAlchemyUserRepository
from backend.infrastructure.db.sqlalchemy.repository.session import SqlAlchemySessionRepository
from backend.infrastructure.db.sqlalchemy.repository.refresh_token import SqlAlchemyRefreshTokenRepository
from backend.infrastructure.db.sqlalchemy.repository.verification import SqlAlchemyVerificationChallengeRepository
from backend.infrastructure.db.sqlalchemy.repository.wallet import SqlAlchemyWalletRepository
from backend.infrastructure.db.sqlalchemy.repository.wallet_balance import SqlAlchemyWalletBalanceRepository
from backend.infrastructure.db.sqlalchemy.repository.ledger_account import SqlAlchemyLedgerAccountRepository
from backend.infrastructure.db.sqlalchemy.repository.outbox import SqlAlchemyOutbox
from backend.infrastructure.db.sqlalchemy.readers.wallet import SqlAlchemyWalletReader


from backend.infrastructure.db.sqlalchemy.repository.transfer import SqlAlchemyTransferRepository
from backend.infrastructure.db.sqlalchemy.repository.sandbox_top_up import SqlAlchemySandboxTopUpRepository
from backend.infrastructure.db.sqlalchemy.repository.ledger_transaction import SqlAlchemyLedgerTransactionRepository
from backend.infrastructure.db.sqlalchemy.repository.idempotency import SqlAlchemyIdempotencyRepository
from backend.infrastructure.db.sqlalchemy.readers.transfer import SqlAlchemyTransferReader
from backend.infrastructure.db.sqlalchemy.readers.history import SqlAlchemyTransactionHistoryReader
from backend.infrastructure.db.sqlalchemy.readers.wallet_balance import SqlAlchemyWalletBalanceReader
from backend.infrastructure.db.sqlalchemy.readers.sandbox_operator import SqlAlchemySandboxOperatorReader


@dataclass(frozen=True)
class _Repositories:
    users: SqlAlchemyUserRepository
    sessions: SqlAlchemySessionRepository
    refresh_tokens: SqlAlchemyRefreshTokenRepository
    verification_challenges: SqlAlchemyVerificationChallengeRepository
    wallets: SqlAlchemyWalletRepository
    wallet_balances: SqlAlchemyWalletBalanceRepository
    ledger_accounts: SqlAlchemyLedgerAccountRepository
    outbox: SqlAlchemyOutbox
    transfers: SqlAlchemyTransferRepository
    sandbox_top_ups: SqlAlchemySandboxTopUpRepository
    ledger_transactions: SqlAlchemyLedgerTransactionRepository
    idempotency: SqlAlchemyIdempotencyRepository


@dataclass(frozen=True)
class _Readers:
    wallets: SqlAlchemyWalletReader
    transfers: SqlAlchemyTransferReader
    history: SqlAlchemyTransactionHistoryReader
    balances: SqlAlchemyWalletBalanceReader
    sandbox_operators: SqlAlchemySandboxOperatorReader


class SqlAlchemyUnitOfWork(
    IUnitOfWork
):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._repositories: _Repositories | None = None
        self._readers: _Readers | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Unit of Work must be entered first")
        return self._session

    def _active_repositories(self) -> _Repositories:
        if self._repositories is None:
            raise RuntimeError("Unit of Work must be entered first")
        return self._repositories

    def _active_readers(self) -> _Readers:
        if self._readers is None:
            raise RuntimeError("Unit of Work must be entered first")
        return self._readers

    @property
    def users(self) -> SqlAlchemyUserRepository:
        return self._active_repositories().users

    @property
    def sessions(self) -> SqlAlchemySessionRepository:
        return self._active_repositories().sessions

    @property
    def refresh_tokens(self) -> SqlAlchemyRefreshTokenRepository:
        return self._active_repositories().refresh_tokens

    @property
    def verification_challenges(self) -> SqlAlchemyVerificationChallengeRepository:
        return self._active_repositories().verification_challenges

    @property
    def wallets(self) -> SqlAlchemyWalletRepository:
        return self._active_repositories().wallets

    @property
    def wallet_balances(self) -> SqlAlchemyWalletBalanceRepository:
        return self._active_repositories().wallet_balances

    @property
    def ledger_accounts(self) -> SqlAlchemyLedgerAccountRepository:
        return self._active_repositories().ledger_accounts

    @property
    def outbox(self) -> SqlAlchemyOutbox:
        return self._active_repositories().outbox

    @property
    def wallet_reader(self) -> SqlAlchemyWalletReader:
        return self._active_readers().wallets

    @property
    def transfers(self) -> SqlAlchemyTransferRepository:
        return self._active_repositories().transfers

    @property
    def sandbox_top_ups(self) -> SqlAlchemySandboxTopUpRepository:
        return self._active_repositories().sandbox_top_ups

    @property
    def ledger_transactions(self) -> SqlAlchemyLedgerTransactionRepository:
        return self._active_repositories().ledger_transactions

    @property
    def idempotency(self) -> SqlAlchemyIdempotencyRepository:
        return self._active_repositories().idempotency

    @property
    def transfer_reader(self) -> SqlAlchemyTransferReader:
        return self._active_readers().transfers

    @property
    def transaction_history_reader(self) -> SqlAlchemyTransactionHistoryReader:
        return self._active_readers().history

    @property
    def wallet_balance_reader(self) -> SqlAlchemyWalletBalanceReader:
        return self._active_readers().balances

    @property
    def sandbox_operator_reader(self) -> SqlAlchemySandboxOperatorReader:
        return self._active_readers().sandbox_operators

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Unit of Work is already active; use a separate instance")
        session = self._session_factory()
        try:
            repositories = _Repositories(
                users=SqlAlchemyUserRepository(session),
                sessions=SqlAlchemySessionRepository(session),
                refresh_tokens=SqlAlchemyRefreshTokenRepository(session),
                verification_challenges=SqlAlchemyVerificationChallengeRepository(session),
                wallets=SqlAlchemyWalletRepository(session),
                wallet_balances=SqlAlchemyWalletBalanceRepository(session),
                ledger_accounts=SqlAlchemyLedgerAccountRepository(session),
                outbox=SqlAlchemyOutbox(session),
                transfers=SqlAlchemyTransferRepository(session),
                sandbox_top_ups=SqlAlchemySandboxTopUpRepository(session),
                ledger_transactions=SqlAlchemyLedgerTransactionRepository(session),
                idempotency=SqlAlchemyIdempotencyRepository(session),

            )
            readers = _Readers(
                wallets=SqlAlchemyWalletReader(session),
                transfers=SqlAlchemyTransferReader(session),
                history=SqlAlchemyTransactionHistoryReader(session),
                balances=SqlAlchemyWalletBalanceReader(session),
                sandbox_operators=SqlAlchemySandboxOperatorReader(session),

            )
        except BaseException:
            await session.close()
            raise
        self._session = session
        self._repositories = repositories
        self._readers = readers
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        session = self.session
        try:
            # Also discard uncommitted work on a normal return without commit.
            await session.rollback()
        finally:
            try:
                await session.close()
            finally:
                self._session = None
                self._repositories = None
                self._readers = None

        if isinstance(exc_val, IntegrityError):
            # asyncpg's original constraint diagnostic is chained by SQLAlchemy.
            original = exc_val.orig
            constraint = getattr(original, "constraint_name", None)
            if constraint is None:
                constraint = getattr(original.__cause__, "constraint_name", None)
            sqlstate = getattr(original, "sqlstate", None)
            if sqlstate == "23505":
                if constraint == "ix_users_email":
                    raise EmailAlreadyExistError() from exc_val
                if constraint == "ix_users_username":
                    raise UsernameAlreadyExistError() from exc_val
                if constraint == "uq_wallets_number":
                    raise WalletNumberAlreadyExistsError() from exc_val

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

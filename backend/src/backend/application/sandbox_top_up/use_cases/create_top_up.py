import hashlib
import json
from dataclasses import dataclass, replace
from uuid import UUID

from backend.application.auth.errors import UserInactiveError
from backend.application.idempotency.errors import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    InvalidIdempotencyKeyError,
)
from backend.application.sandbox_top_up.dtos.create_top_up import CreateSandboxTopUpCommand, CreateSandboxTopUpResult
from backend.application.sandbox_top_up.errors import (
    SandboxDisabledError,
    SandboxFundingAccountError,
    SandboxOperatorRequiredError,
    SandboxTopUpCurrencyMismatchError,
    SandboxTopUpLimitExceededError,
)
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.errors import WalletAccountingStateError, WalletNotFoundError
from backend.domain.ledger_account.enums import AccountType
from backend.domain.ledger_transaction.entities import LedgerTransaction
from backend.domain.sandbox_top_up.entities import MAX_SANDBOX_TOP_UP_AMOUNT_MINOR, SandboxTopUp
from backend.domain.sandbox_top_up.errors import InvalidSandboxTopUpAmountError
from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.errors import WalletNotActiveError

SANDBOX_TOP_UP_IDEMPOTENCY_SCOPE = "sandbox_top_up.create"


@dataclass(frozen=True)
class CreateSandboxTopUpUseCase:
    uow: IUnitOfWork
    clock: IClock
    sandbox_enabled: bool = False
    max_amount_minor: int = MAX_SANDBOX_TOP_UP_AMOUNT_MINOR

    def __post_init__(self) -> None:
        if type(self.sandbox_enabled) is not bool:
            raise ValueError("Sandbox enabled must be a boolean")
        if type(self.max_amount_minor) is not int or not 0 < self.max_amount_minor <= MAX_SANDBOX_TOP_UP_AMOUNT_MINOR:
            raise ValueError("Top-up limit must be a positive signed BIGINT")

    async def execute(
            self,
            cmd: CreateSandboxTopUpCommand
    ) -> CreateSandboxTopUpResult:
        self._validate_command(cmd)
        payload_hash = self._payload_hash(cmd)

        async with self.uow:
            user = await self.uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()
            if not await self.uow.sandbox_operator_reader.is_operator(user.id):
                raise SandboxOperatorRequiredError()

            previous = await self.uow.idempotency.claim(
                user_id=cmd.user_id,
                scope=SANDBOX_TOP_UP_IDEMPOTENCY_SCOPE,
                key=cmd.idempotency_key,
                payload_hash=payload_hash,
            )
            if previous is not None:
                if previous.payload_hash != payload_hash:
                    raise IdempotencyConflictError()
                if previous.resource_id is None:
                    raise IdempotencyInProgressError()
                return CreateSandboxTopUpResult(top_up_id=previous.resource_id)

            # Permission grants/revocations serialize on the actor's user row.
            user = await self.uow.users.get_by_id_for_update(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()
            if not await self.uow.sandbox_operator_reader.is_operator(user.id):
                raise SandboxOperatorRequiredError()

            # Disabling sandbox or lowering a limit stops new money movements,
            # while an authorized replay may still recover its old result.
            if not self.sandbox_enabled:
                raise SandboxDisabledError()
            if cmd.amount_minor > self.max_amount_minor:
                raise SandboxTopUpLimitExceededError()

            wallet = await self.uow.wallets.get_by_id_for_update(wallet_id=cmd.wallet_id)
            if wallet is None or wallet.id != cmd.wallet_id:
                raise WalletNotFoundError()
            if not wallet.is_active():
                raise WalletNotActiveError()
            if wallet.currency != cmd.currency:
                raise SandboxTopUpCurrencyMismatchError()

            balance = await self.uow.wallet_balances.get_by_wallet_id_for_update(wallet_id=wallet.id)
            if balance is None or balance.wallet_id != wallet.id:
                raise WalletAccountingStateError()
            balance = replace(balance)

            # Follow wallet -> balance -> wallet account. System funding is
            # always locked after wallet accounts, with no later financial locks.
            account = await self.uow.ledger_accounts.get_by_wallet_id_for_update(wallet_id=wallet.id)
            if (
                account is None
                or account.wallet_id != wallet.id
                or account.currency != cmd.currency
                or account.account_type != AccountType.LIABILITY
            ):
                raise WalletAccountingStateError()
            account.ensure_active()

            funding_account = await self.uow.ledger_accounts.get_sandbox_funding_for_update(currency=cmd.currency)
            if (
                funding_account is None
                or funding_account.wallet_id is not None
                or funding_account.currency != cmd.currency
                or funding_account.account_type != AccountType.ASSET
                or funding_account.code.value != f"SYS:SIM_FUNDING:{cmd.currency.value}"
                or funding_account.id == account.id
            ):
                raise SandboxFundingAccountError()
            funding_account.ensure_active()

            now = self.clock.now()
            top_up = SandboxTopUp.create(
                wallet_id=wallet.id,
                initiated_by_user_id=user.id,
                amount_minor=cmd.amount_minor,
                currency=cmd.currency,
                now=now,
            )
            balance.credit(amount_minor=cmd.amount_minor, now=now)
            top_up.complete(now=now)
            journal = LedgerTransaction.for_sandbox_top_up(
                top_up=top_up,
                funding_account=funding_account,
                wallet_account=account,
                now=now,
            )

            await self.uow.sandbox_top_ups.add(top_up)
            await self.uow.ledger_transactions.add(journal)
            await self.uow.wallet_balances.save(balance)
            await self.uow.idempotency.complete(
                user_id=cmd.user_id,
                scope=SANDBOX_TOP_UP_IDEMPOTENCY_SCOPE,
                key=cmd.idempotency_key,
                payload_hash=payload_hash,
                resource_id=top_up.id,
            )
            await self.uow.commit()

        return CreateSandboxTopUpResult(top_up_id=top_up.id)

    def _validate_command(self, cmd: CreateSandboxTopUpCommand) -> None:
        for value in (cmd.user_id, cmd.wallet_id):
            if not isinstance(value, UUID):
                raise TypeError("User and wallet IDs must be UUIDs")
        if type(cmd.amount_minor) is not int or not 0 < cmd.amount_minor <= MAX_SANDBOX_TOP_UP_AMOUNT_MINOR:
            raise InvalidSandboxTopUpAmountError("Amount must be a positive signed BIGINT")
        if not isinstance(cmd.currency, CurrencyEnum):
            raise TypeError("Currency must be a CurrencyEnum")
        if (
            not isinstance(cmd.idempotency_key, str)
            or not 1 <= len(cmd.idempotency_key) <= 255
            or any(not 33 <= ord(char) <= 126 for char in cmd.idempotency_key)
        ):
            raise InvalidIdempotencyKeyError()

    @staticmethod
    def _payload_hash(cmd: CreateSandboxTopUpCommand) -> str:
        payload = json.dumps(
            {
                "wallet_id": str(cmd.wallet_id),
                "amount_minor": cmd.amount_minor,
                "currency": cmd.currency.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

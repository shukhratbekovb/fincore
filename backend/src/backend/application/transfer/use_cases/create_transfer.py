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
from backend.application.share.interfaces.clock import IClock
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.transfer.dtos.create_transfer import CreateTransferCommand, CreateTransferResult
from backend.application.transfer.errors import TransferCurrencyMismatchError, TransferLimitExceededError
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.errors import WalletAccountingStateError, WalletNotFoundError
from backend.domain.ledger_account.enums import AccountType
from backend.domain.ledger_transaction.entities import LedgerTransaction
from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.entities import MAX_TRANSFER_AMOUNT_MINOR, Transfer
from backend.domain.transfer.errors import InvalidTransferAmountError, SameWalletTransferError
from backend.domain.wallet.errors import WalletNotActiveError

TRANSFER_IDEMPOTENCY_SCOPE = "transfer.create"


@dataclass(frozen=True)
class CreateTransferUseCase:
    uow: IUnitOfWork
    clock: IClock
    max_amount_minor: int = MAX_TRANSFER_AMOUNT_MINOR

    def __post_init__(self) -> None:
        if type(self.max_amount_minor) is not int or not 0 < self.max_amount_minor <= MAX_TRANSFER_AMOUNT_MINOR:
            raise ValueError("Transfer limit must be a positive signed BIGINT")

    async def execute(
            self,
            cmd: CreateTransferCommand
    ) -> CreateTransferResult:
        self._validate_command(cmd)
        payload_hash = self._payload_hash(cmd)

        async with self.uow:
            # Authenticate the actor before exposing a cached command result.
            user = await self.uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            previous = await self.uow.idempotency.claim(
                user_id=cmd.user_id,
                scope=TRANSFER_IDEMPOTENCY_SCOPE,
                key=cmd.idempotency_key,
                payload_hash=payload_hash,
            )
            if previous is not None:
                if previous.payload_hash != payload_hash:
                    raise IdempotencyConflictError()
                if previous.resource_id is None:
                    raise IdempotencyInProgressError()
                return CreateTransferResult(transfer_id=previous.resource_id)

            # Serialize actor status changes, then lock each financial group by
            # wallet ID. CloseWallet follows wallet -> balance -> account too.
            user = await self.uow.users.get_by_id_for_update(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            if cmd.amount_minor > self.max_amount_minor:
                raise TransferLimitExceededError()

            wallet_ids = sorted((cmd.sender_wallet_id, cmd.receiver_wallet_id))
            wallets = {}
            for wallet_id in wallet_ids:
                wallet = await self.uow.wallets.get_by_id_for_update(wallet_id=wallet_id)
                if wallet is None or wallet.id != wallet_id:
                    raise WalletNotFoundError()
                if wallet_id == cmd.sender_wallet_id and wallet.user_id != user.id:
                    raise WalletNotFoundError()
                wallets[wallet_id] = wallet

            for wallet in wallets.values():
                if not wallet.is_active():
                    raise WalletNotActiveError()
                if wallet.currency != cmd.currency:
                    raise TransferCurrencyMismatchError()

            balances = {}
            for wallet_id in wallet_ids:
                balance = await self.uow.wallet_balances.get_by_wallet_id_for_update(wallet_id=wallet_id)
                if balance is None or balance.wallet_id != wallet_id:
                    raise WalletAccountingStateError()
                # Work on validated copies. A later failed debit/credit must not
                # leave a repository-owned object partially changed in memory.
                balances[wallet_id] = replace(balance)

            accounts = {}
            for wallet_id in wallet_ids:
                account = await self.uow.ledger_accounts.get_by_wallet_id_for_update(wallet_id=wallet_id)
                if (
                    account is None
                    or account.wallet_id != wallet_id
                    or account.currency != cmd.currency
                    or account.account_type != AccountType.LIABILITY
                ):
                    raise WalletAccountingStateError()
                account.ensure_active()
                accounts[wallet_id] = account

            now = self.clock.now()

            transfer = Transfer.create(
                sender_wallet_id=cmd.sender_wallet_id,
                receiver_wallet_id=cmd.receiver_wallet_id,
                amount_minor=cmd.amount_minor,
                currency=cmd.currency,
                now=now
            )

            balances[cmd.sender_wallet_id].debit(amount_minor=cmd.amount_minor, now=now)
            balances[cmd.receiver_wallet_id].credit(amount_minor=cmd.amount_minor, now=now)
            transfer.complete(now=now)

            journal = LedgerTransaction.for_transfer(
                transfer=transfer,
                sender_account=accounts[cmd.sender_wallet_id],
                receiver_account=accounts[cmd.receiver_wallet_id],
                now=now,
            )

            await self.uow.transfers.add(transfer)
            await self.uow.ledger_transactions.add(journal)
            for balance in balances.values():
                await self.uow.wallet_balances.save(balance)
            await self.uow.idempotency.complete(
                user_id=cmd.user_id,
                scope=TRANSFER_IDEMPOTENCY_SCOPE,
                key=cmd.idempotency_key,
                payload_hash=payload_hash,
                resource_id=transfer.id,
            )
            await self.uow.commit()

        return CreateTransferResult(transfer_id=transfer.id)

    def _validate_command(self, cmd: CreateTransferCommand) -> None:
        for value in (cmd.user_id, cmd.sender_wallet_id, cmd.receiver_wallet_id):
            if not isinstance(value, UUID):
                raise TypeError("User and wallet IDs must be UUIDs")
        if cmd.sender_wallet_id == cmd.receiver_wallet_id:
            raise SameWalletTransferError()
        if type(cmd.amount_minor) is not int or not 0 < cmd.amount_minor <= MAX_TRANSFER_AMOUNT_MINOR:
            raise InvalidTransferAmountError("Amount must be a positive signed BIGINT")
        if not isinstance(cmd.currency, CurrencyEnum):
            raise TypeError("Currency must be a CurrencyEnum")
        if (
            not isinstance(cmd.idempotency_key, str)
            or not 1 <= len(cmd.idempotency_key) <= 255
            or any(not 33 <= ord(char) <= 126 for char in cmd.idempotency_key)
        ):
            raise InvalidIdempotencyKeyError()

    @staticmethod
    def _payload_hash(cmd: CreateTransferCommand) -> str:
        payload = json.dumps(
            {
                "sender_wallet_id": str(cmd.sender_wallet_id),
                "receiver_wallet_id": str(cmd.receiver_wallet_id),
                "amount_minor": cmd.amount_minor,
                "currency": cmd.currency.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

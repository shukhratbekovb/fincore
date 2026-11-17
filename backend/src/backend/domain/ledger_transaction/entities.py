from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Self
from uuid import UUID, uuid4

from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_entry.entities import LedgerEntry
from backend.domain.ledger_entry.enums import LedgerEntrySideEnum
from backend.domain.ledger_transaction.enums import LedgerTransactionKindEnum
from backend.domain.ledger_transaction.errors import InvalidLedgerTransactionError, UnbalancedLedgerTransactionError
from backend.domain.sandbox_top_up.entities import SandboxTopUp
from backend.domain.sandbox_top_up.enums import SandboxTopUpStatusEnum
from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.entities import Transfer
from backend.domain.transfer.enums import TransferStatusEnum


@dataclass(frozen=True, kw_only=True)
class LedgerTransaction:
    """Immutable, balanced journal aggregate, restored with all its entries.

    Factories check account/source relationships. Persistence must additionally
    enforce unique source links, account currencies and immutability, and commit
    the journal together with its business operation and balance projection.
    """

    kind: LedgerTransactionKindEnum
    currency: CurrencyEnum
    posted_at: datetime
    entries: tuple[LedgerEntry, ...]
    transfer_id: UUID | None = field(default=None)
    sandbox_top_up_id: UUID | None = field(default=None)
    reference: str | None = field(default=None)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("Transaction ID must be a UUID")
        for value in (self.transfer_id, self.sandbox_top_up_id):
            if value is not None and not isinstance(value, UUID):
                raise TypeError("Source IDs must be UUIDs")
        if not isinstance(self.kind, LedgerTransactionKindEnum):
            raise TypeError("Kind must be a LedgerTransactionKindEnum")
        if not isinstance(self.currency, CurrencyEnum):
            raise TypeError("Currency must be a CurrencyEnum")
        if not isinstance(self.posted_at, datetime) or self.posted_at.tzinfo is None or self.posted_at.utcoffset() is None:
            raise InvalidLedgerTransactionError("Posting time must be a timezone-aware datetime")
        if (self.transfer_id is None) == (self.sandbox_top_up_id is None):
            raise InvalidLedgerTransactionError("Journal must have exactly one business source")
        if (self.kind == LedgerTransactionKindEnum.P2P_TRANSFER) != (self.transfer_id is not None):
            raise InvalidLedgerTransactionError("Journal kind must match its source")
        if self.reference is not None:
            if not isinstance(self.reference, str) or not self.reference.strip() or len(self.reference) > 128:
                raise InvalidLedgerTransactionError("Reference must be a nonblank string of at most 128 characters")
        if not isinstance(self.entries, tuple) or len(self.entries) < 2:
            raise InvalidLedgerTransactionError("Journal requires an immutable tuple of at least two entries")

        ids = set()
        account_sides = set()
        debit_total = credit_total = 0
        for entry in self.entries:
            if not isinstance(entry, LedgerEntry):
                raise TypeError("Journal entries must be LedgerEntry objects")
            if entry.ledger_transaction_id != self.id or entry.currency != self.currency:
                raise InvalidLedgerTransactionError("Entry must belong to this journal and currency")
            if entry.created_at != self.posted_at:
                raise InvalidLedgerTransactionError("Entry time must match journal posting time")
            account_side = (entry.ledger_account_id, entry.side)
            if entry.id in ids or account_side in account_sides:
                raise InvalidLedgerTransactionError("Duplicate entry ID or account/side pair")
            ids.add(entry.id)
            account_sides.add(account_side)
            if entry.side == LedgerEntrySideEnum.DEBIT:
                debit_total += entry.amount_minor
            else:
                credit_total += entry.amount_minor
        if debit_total != credit_total:
            raise UnbalancedLedgerTransactionError("Total debits must equal total credits")

    @classmethod
    def for_transfer(
            cls,
            *,
            transfer: Transfer,
            sender_account: LedgerAccount,
            receiver_account: LedgerAccount,
            now: datetime,
            reference: str | None = None,
    ) -> Self:
        if not isinstance(transfer, Transfer):
            raise TypeError("Source must be a Transfer")
        # Snapshot and revalidate the mutable source before deriving a journal.
        transfer = replace(transfer)
        if transfer.status != TransferStatusEnum.COMPLETED:
            raise InvalidLedgerTransactionError("Only completed transfers may have a journal")
        if not isinstance(sender_account, LedgerAccount) or not isinstance(receiver_account, LedgerAccount):
            raise TypeError("Posting accounts must be LedgerAccount objects")
        if sender_account.wallet_id != transfer.sender_wallet_id or receiver_account.wallet_id != transfer.receiver_wallet_id:
            raise InvalidLedgerTransactionError("Posting accounts must match transfer wallets")
        return cls._for_operation(
            debit_account=sender_account,
            credit_account=receiver_account,
            amount_minor=transfer.amount_minor,
            currency=transfer.currency,
            completed_at=transfer.completed_at,
            now=now,
            kind=LedgerTransactionKindEnum.P2P_TRANSFER,
            transfer_id=transfer.id,
            reference=reference,
        )

    @classmethod
    def for_sandbox_top_up(
            cls,
            *,
            top_up: SandboxTopUp,
            funding_account: LedgerAccount,
            wallet_account: LedgerAccount,
            now: datetime,
            reference: str | None = None,
    ) -> Self:
        if not isinstance(top_up, SandboxTopUp):
            raise TypeError("Source must be a SandboxTopUp")
        top_up = replace(top_up)
        if top_up.status != SandboxTopUpStatusEnum.COMPLETED:
            raise InvalidLedgerTransactionError("Only completed top-ups may have a journal")
        if not isinstance(funding_account, LedgerAccount) or not isinstance(wallet_account, LedgerAccount):
            raise TypeError("Posting accounts must be LedgerAccount objects")
        if funding_account.wallet_id is not None or wallet_account.wallet_id != top_up.wallet_id:
            raise InvalidLedgerTransactionError("Posting requires system funding and the destination wallet account")
        return cls._for_operation(
            debit_account=funding_account,
            credit_account=wallet_account,
            amount_minor=top_up.amount_minor,
            currency=top_up.currency,
            completed_at=top_up.completed_at,
            now=now,
            kind=LedgerTransactionKindEnum.SANDBOX_TOPUP,
            sandbox_top_up_id=top_up.id,
            reference=reference,
        )

    @classmethod
    def _for_operation(
            cls,
            *,
            debit_account: LedgerAccount,
            credit_account: LedgerAccount,
            amount_minor: int,
            currency: CurrencyEnum,
            completed_at: datetime,
            now: datetime,
            kind: LedgerTransactionKindEnum,
            transfer_id: UUID | None = None,
            sandbox_top_up_id: UUID | None = None,
            reference: str | None = None,
    ) -> Self:
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise InvalidLedgerTransactionError("Posting time must be a timezone-aware datetime")
        if now < completed_at:
            raise InvalidLedgerTransactionError("Posting cannot precede operation completion")
        transaction_id = uuid4()
        entries = tuple(
            LedgerEntry.create(
                ledger_transaction_id=transaction_id,
                account=account,
                side=side,
                amount_minor=amount_minor,
                currency=currency,
                now=now,
            )
            for account, side in (
                (debit_account, LedgerEntrySideEnum.DEBIT),
                (credit_account, LedgerEntrySideEnum.CREDIT),
            )
        )
        return cls(
            id=transaction_id,
            kind=kind,
            currency=currency,
            posted_at=now,
            entries=entries,
            transfer_id=transfer_id,
            sandbox_top_up_id=sandbox_top_up_id,
            reference=reference,
        )

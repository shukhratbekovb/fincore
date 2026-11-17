from dataclasses import dataclass, field
from datetime import datetime
from typing import Self
from uuid import UUID, uuid4

from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_entry.enums import LedgerEntrySideEnum
from backend.domain.ledger_entry.errors import InvalidLedgerEntryError
from backend.domain.share.enums import CurrencyEnum

MAX_LEDGER_ENTRY_AMOUNT_MINOR = 2 ** 63 - 1


@dataclass(frozen=True, kw_only=True)
class LedgerEntry:
    """Immutable journal line; a standalone line does not represent a posting."""

    ledger_transaction_id: UUID
    ledger_account_id: UUID
    side: LedgerEntrySideEnum
    amount_minor: int
    currency: CurrencyEnum
    created_at: datetime
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        for value in (self.id, self.ledger_transaction_id, self.ledger_account_id):
            if not isinstance(value, UUID):
                raise TypeError("Entry, transaction and account IDs must be UUIDs")
        if not isinstance(self.side, LedgerEntrySideEnum):
            raise TypeError("Side must be a LedgerEntrySideEnum")
        if not isinstance(self.currency, CurrencyEnum):
            raise TypeError("Currency must be a CurrencyEnum")
        if type(self.amount_minor) is not int or not 0 < self.amount_minor <= MAX_LEDGER_ENTRY_AMOUNT_MINOR:
            raise InvalidLedgerEntryError("Amount must be a positive signed BIGINT")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise InvalidLedgerEntryError("Creation time must be a timezone-aware datetime")

    @classmethod
    def create(
            cls,
            *,
            ledger_transaction_id: UUID,
            account: LedgerAccount,
            side: LedgerEntrySideEnum,
            amount_minor: int,
            currency: CurrencyEnum,
            now: datetime,
    ) -> Self:
        if not isinstance(account, LedgerAccount):
            raise TypeError("Account must be a LedgerAccount")
        account.ensure_active()
        if not isinstance(currency, CurrencyEnum):
            raise TypeError("Currency must be a CurrencyEnum")
        if account.currency != currency:
            raise InvalidLedgerEntryError("Entry currency must match account currency")
        return cls(
            ledger_transaction_id=ledger_transaction_id,
            ledger_account_id=account.id,
            side=side,
            amount_minor=amount_minor,
            currency=currency,
            created_at=now,
        )

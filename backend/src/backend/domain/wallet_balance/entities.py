from dataclasses import dataclass
from datetime import datetime
from typing import Self
from uuid import UUID

from backend.domain.share.entities import BaseEntity
from backend.domain.share.mixins import TimeActionMixin
from backend.domain.wallet_balance.errors import (
    InsufficientFundsError,
    InvalidBalanceAmountError,
    InvalidWalletBalanceError,
    WalletBalanceOverflowError,
)

MAX_BALANCE_MINOR = 2 ** 63 - 1


@dataclass(kw_only=True)
class WalletBalance(TimeActionMixin, BaseEntity):
    """Synchronous ledger projection identified by wallet_id, not a separate UUID.

    Mutations require a locked row and corresponding ledger entries in the same
    transaction. These methods alone do not represent a completed money operation.
    """

    wallet_id: UUID
    posted_minor: int = 0
    version: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.wallet_id, UUID):
            raise TypeError("Wallet ID must be a UUID")
        if type(self.posted_minor) is not int or not 0 <= self.posted_minor <= MAX_BALANCE_MINOR:
            raise InvalidWalletBalanceError("Balance must be a nonnegative signed BIGINT")
        if type(self.version) is not int or not 0 <= self.version <= MAX_BALANCE_MINOR:
            raise InvalidWalletBalanceError("Version must be a nonnegative signed BIGINT")
        self._require_aware_time(self.created_at)
        self._require_aware_time(self.updated_at)

    @classmethod
    def create(cls, *, wallet_id: UUID, now: datetime) -> Self:
        return cls(wallet_id=wallet_id, created_at=now, updated_at=now)

    @property
    def available_minor(self) -> int:
        return self.posted_minor

    def credit(self, amount_minor: int, *, now: datetime) -> None:
        self._validate_change(amount_minor, now)
        if self.posted_minor + amount_minor > MAX_BALANCE_MINOR:
            raise WalletBalanceOverflowError()
        self.posted_minor += amount_minor
        self.version += 1
        self.updated_at = now

    def debit(self, amount_minor: int, *, now: datetime) -> None:
        self._validate_change(amount_minor, now)
        if amount_minor > self.posted_minor:
            raise InsufficientFundsError()
        self.posted_minor -= amount_minor
        self.version += 1
        self.updated_at = now

    def _validate_change(self, amount_minor: int, now: datetime) -> None:
        if type(amount_minor) is not int or not 0 < amount_minor <= MAX_BALANCE_MINOR:
            raise InvalidBalanceAmountError("Amount must be a positive signed BIGINT")
        self._require_aware_time(now)
        if self.version == MAX_BALANCE_MINOR:
            raise WalletBalanceOverflowError("Balance version overflow")

    @staticmethod
    def _require_aware_time(value: datetime) -> None:
        if not isinstance(value, datetime):
            raise TypeError("Balance timestamps must be datetimes")
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidWalletBalanceError("Balance timestamps must be timezone-aware")

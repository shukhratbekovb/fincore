from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.application.wallet.errors import WalletAccountingStateError
from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet_balance.entities import MAX_BALANCE_MINOR


def _require_aware_time(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WalletAccountingStateError("Balance projection timestamps must be timezone-aware")


@dataclass(frozen=True, kw_only=True)
class CurrencyBalanceDTO:
    currency: CurrencyEnum
    posted_minor: int
    available_minor: int
    spendable_minor: int

    def __post_init__(self) -> None:
        if not isinstance(self.currency, CurrencyEnum):
            raise TypeError("Currency must be a CurrencyEnum")
        if any(type(value) is not int or value < 0 for value in (
            self.posted_minor, self.available_minor, self.spendable_minor,
        )):
            raise WalletAccountingStateError("Balance amounts must be nonnegative integers")
        if not self.spendable_minor <= self.available_minor <= self.posted_minor:
            raise WalletAccountingStateError("Expected spendable <= available <= posted")


@dataclass(frozen=True, kw_only=True)
class WalletBalanceDTO(CurrencyBalanceDTO):
    wallet_id: UUID
    version: int
    updated_at: datetime
    as_of: datetime

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.wallet_id, UUID):
            raise TypeError("Wallet ID must be a UUID")
        if self.posted_minor > MAX_BALANCE_MINOR or type(self.version) is not int or not 0 <= self.version <= MAX_BALANCE_MINOR:
            raise WalletAccountingStateError("Wallet balance and version must fit signed BIGINT")
        _require_aware_time(self.updated_at)
        _require_aware_time(self.as_of)


@dataclass(frozen=True, kw_only=True)
class BalanceSummaryDTO:
    totals: list[CurrencyBalanceDTO]
    as_of: datetime

    def __post_init__(self) -> None:
        _require_aware_time(self.as_of)
        if not isinstance(self.totals, list) or any(not isinstance(item, CurrencyBalanceDTO) for item in self.totals):
            raise WalletAccountingStateError("Summary must contain currency balance projections")
        if len({item.currency for item in self.totals}) != len(self.totals):
            raise WalletAccountingStateError("Summary must contain at most one total per currency")

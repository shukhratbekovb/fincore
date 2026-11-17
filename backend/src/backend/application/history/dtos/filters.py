from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from backend.application.history.errors import InvalidTransactionFilterError
from backend.domain.ledger_transaction.enums import LedgerTransactionKindEnum
from backend.domain.share.enums import CurrencyEnum


class TransactionDirectionEnum(str, Enum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    INTERNAL = "internal"


@dataclass(frozen=True, kw_only=True)
class TransactionFilter:
    kind: LedgerTransactionKindEnum | None = None
    currency: CurrencyEnum | None = None
    direction: TransactionDirectionEnum | None = None
    posted_from: datetime | None = None
    posted_to: datetime | None = None

    def __post_init__(self) -> None:
        for value, expected_type in (
            (self.kind, LedgerTransactionKindEnum),
            (self.currency, CurrencyEnum),
            (self.direction, TransactionDirectionEnum),
        ):
            if value is not None and not isinstance(value, expected_type):
                raise InvalidTransactionFilterError()
        for value in (self.posted_from, self.posted_to):
            if value is not None and (
                not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None
            ):
                raise InvalidTransactionFilterError()
        if self.posted_from is not None and self.posted_to is not None and self.posted_from >= self.posted_to:
            raise InvalidTransactionFilterError("Posting range must have start before end")


@dataclass(frozen=True, kw_only=True)
class WalletTransactionFilter(TransactionFilter):
    def __post_init__(self) -> None:
        super().__post_init__()
        if self.direction == TransactionDirectionEnum.INTERNAL:
            raise InvalidTransactionFilterError("Single-wallet direction must be incoming or outgoing")


@dataclass(frozen=True, kw_only=True)
class MyTransactionsFilter(TransactionFilter):
    wallet_id: UUID | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.wallet_id is not None:
            if not isinstance(self.wallet_id, UUID):
                raise InvalidTransactionFilterError()
            if self.direction == TransactionDirectionEnum.INTERNAL:
                raise InvalidTransactionFilterError("Wallet-filtered direction must be incoming or outgoing")

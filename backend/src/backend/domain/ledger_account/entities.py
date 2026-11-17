from dataclasses import dataclass, field
from datetime import datetime
from typing import Self
from uuid import UUID, uuid4

from backend.domain.ledger_account.enums import AccountStatus, AccountType
from backend.domain.ledger_account.errors import (
    InvalidLedgerAccountError,
    LedgerAccountClosedError,
)
from backend.domain.ledger_account.value_objects import LedgerAccountCode
from backend.domain.share.enums import CurrencyEnum


@dataclass(frozen=True, kw_only=True)
class LedgerAccount:
    """Accounting identity is immutable; only close() may change the status.

    Mutable dataclass mixins are deliberately not inherited. Balance/entries,
    authorization and checks required before closing belong to other objects.
    """

    code: LedgerAccountCode
    account_type: AccountType
    currency: CurrencyEnum
    created_at: datetime
    wallet_id: UUID | None = None
    status: AccountStatus = AccountStatus.ACTIVE
    id: UUID = field(default_factory=uuid4)

    # close() changes status, so entities must not be used as hash keys.
    __hash__ = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("Ledger account ID must be a UUID")
        if self.wallet_id is not None and not isinstance(self.wallet_id, UUID):
            raise TypeError("Wallet ID must be a UUID")
        if not isinstance(self.code, LedgerAccountCode):
            raise TypeError("Code must be a LedgerAccountCode")
        if not isinstance(self.account_type, AccountType):
            raise TypeError("Account type must be an AccountType")
        self._require_currency(self.currency)
        if not isinstance(self.status, AccountStatus):
            raise TypeError("Account status must be an AccountStatus")
        if not isinstance(self.created_at, datetime):
            raise TypeError("Creation time must be a datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise InvalidLedgerAccountError("Creation time must be timezone-aware")

        if self.wallet_id is not None:
            expected_type = AccountType.LIABILITY
            expected_code = f"WALLET:{self.wallet_id}:{self.currency.value}"
        else:
            expected_type = AccountType.ASSET
            expected_code = f"SYS:SIM_FUNDING:{self.currency.value}"
        if self.account_type != expected_type or self.code.value != expected_code:
            raise InvalidLedgerAccountError(
                "Account type and code must match its wallet/system purpose and currency"
            )

    @classmethod
    def for_wallet(cls, *, wallet_id: UUID, currency: CurrencyEnum, now: datetime) -> Self:
        if not isinstance(wallet_id, UUID):
            raise TypeError("Wallet ID must be a UUID")
        cls._require_currency(currency)
        return cls(
            wallet_id=wallet_id,
            code=LedgerAccountCode(f"WALLET:{wallet_id}:{currency.value}"),
            account_type=AccountType.LIABILITY,
            currency=currency,
            created_at=now,
        )

    @classmethod
    def for_sandbox_funding(cls, *, currency: CurrencyEnum, now: datetime) -> Self:
        cls._require_currency(currency)
        return cls(
            code=LedgerAccountCode(f"SYS:SIM_FUNDING:{currency.value}"),
            account_type=AccountType.ASSET,
            currency=currency,
            created_at=now,
        )

    def is_active(self) -> bool:
        return self.status == AccountStatus.ACTIVE

    def ensure_active(self) -> None:
        """Posting must check this inside its transaction, before adding entries."""
        if not self.is_active():
            raise LedgerAccountClosedError()

    def close(self) -> None:
        """Caller must first check balance and closing policy in its transaction."""
        object.__setattr__(self, "status", AccountStatus.CLOSED)

    @staticmethod
    def _require_currency(currency: CurrencyEnum) -> None:
        if not isinstance(currency, CurrencyEnum):
            raise TypeError("Currency must be a CurrencyEnum")

from dataclasses import dataclass, field
from datetime import datetime
from typing import Self
from uuid import UUID

from backend.domain.sandbox_top_up.enums import SandboxTopUpRejectionCodeEnum, SandboxTopUpStatusEnum
from backend.domain.sandbox_top_up.errors import (
    InvalidSandboxTopUpAmountError,
    InvalidSandboxTopUpStateError,
    SandboxTopUpNotPendingError,
)
from backend.domain.share.entities import BaseEntity
from backend.domain.share.enums import CurrencyEnum
from backend.domain.share.mixins import IdentityMixin, TimeActionMixin

MAX_SANDBOX_TOP_UP_AMOUNT_MINOR = 2 ** 63 - 1


@dataclass(kw_only=True)
class SandboxTopUp(IdentityMixin, TimeActionMixin, BaseEntity):
    """Virtual funding operation, not an external payment.

    Authorization, configured limits and sandbox availability belong to the use
    case. PENDING must not be committed; completion needs an atomic posting.
    """

    wallet_id: UUID
    initiated_by_user_id: UUID
    amount_minor: int
    currency: CurrencyEnum
    status: SandboxTopUpStatusEnum
    rejection_code: SandboxTopUpRejectionCodeEnum | None = field(default=None)
    completed_at: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        for value in (self.id, self.wallet_id, self.initiated_by_user_id):
            if not isinstance(value, UUID):
                raise TypeError("Top-up, wallet and initiator IDs must be UUIDs")
        if type(self.amount_minor) is not int or not 0 < self.amount_minor <= MAX_SANDBOX_TOP_UP_AMOUNT_MINOR:
            raise InvalidSandboxTopUpAmountError("Amount must be a positive signed BIGINT")
        if not isinstance(self.currency, CurrencyEnum):
            raise TypeError("Currency must be a CurrencyEnum")
        if not isinstance(self.status, SandboxTopUpStatusEnum):
            raise TypeError("Status must be a SandboxTopUpStatusEnum")
        self._require_aware_time(self.created_at)
        self._require_aware_time(self.updated_at)
        if self.updated_at < self.created_at:
            raise InvalidSandboxTopUpStateError("Update time cannot precede creation")
        if self.status == SandboxTopUpStatusEnum.COMPLETED:
            self._require_aware_time(self.completed_at)
            if not self.created_at <= self.completed_at <= self.updated_at:
                raise InvalidSandboxTopUpStateError("Completion time must be between creation and update")
            if self.rejection_code is not None:
                raise InvalidSandboxTopUpStateError("Completed top-up cannot have a rejection code")
        else:
            if self.completed_at is not None:
                raise InvalidSandboxTopUpStateError("Only completed top-ups may have a completion time")
            if self.status == SandboxTopUpStatusEnum.REJECTED:
                self._require_rejection_code(self.rejection_code)
            elif self.rejection_code is not None:
                raise InvalidSandboxTopUpStateError("Pending top-up cannot have a rejection code")

    @classmethod
    def create(
            cls,
            *,
            wallet_id: UUID,
            initiated_by_user_id: UUID,
            amount_minor: int,
            currency: CurrencyEnum,
            now: datetime,
    ) -> Self:
        return cls(
            wallet_id=wallet_id,
            initiated_by_user_id=initiated_by_user_id,
            amount_minor=amount_minor,
            currency=currency,
            status=SandboxTopUpStatusEnum.PENDING,
            created_at=now,
            updated_at=now,
        )

    def complete(self, now: datetime) -> None:
        self._ensure_pending()
        self._validate_transition_time(now)
        self.status = SandboxTopUpStatusEnum.COMPLETED
        self.completed_at = now
        self.updated_at = now

    def reject(
            self,
            rejection_code: SandboxTopUpRejectionCodeEnum,
            *,
            now: datetime,
    ) -> None:
        self._ensure_pending()
        self._require_rejection_code(rejection_code)
        self._validate_transition_time(now)
        self.status = SandboxTopUpStatusEnum.REJECTED
        self.rejection_code = rejection_code
        self.updated_at = now

    def _ensure_pending(self) -> None:
        if self.status != SandboxTopUpStatusEnum.PENDING:
            raise SandboxTopUpNotPendingError()

    def _validate_transition_time(self, now: datetime) -> None:
        self._require_aware_time(now)
        if now < self.updated_at:
            raise InvalidSandboxTopUpStateError("Transition time cannot precede the last update")

    @staticmethod
    def _require_aware_time(value: datetime) -> None:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise InvalidSandboxTopUpStateError("Top-up timestamps must be timezone-aware datetimes")

    @staticmethod
    def _require_rejection_code(value: SandboxTopUpRejectionCodeEnum) -> None:
        if not isinstance(value, SandboxTopUpRejectionCodeEnum):
            raise InvalidSandboxTopUpStateError("Rejection code must be a SandboxTopUpRejectionCodeEnum")

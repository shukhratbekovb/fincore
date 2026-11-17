from dataclasses import dataclass, field
from datetime import datetime
from typing import Self
from uuid import UUID

from backend.domain.share.entities import BaseEntity
from backend.domain.share.enums import CurrencyEnum
from backend.domain.share.mixins import IdentityMixin, TimeActionMixin
from backend.domain.transfer.enums import TransferRejectionCodeEnum, TransferStatusEnum
from backend.domain.transfer.errors import (
    InvalidTransferAmountError,
    InvalidTransferStateError,
    SameWalletTransferError,
    TransferNotPendingError,
)

MAX_TRANSFER_AMOUNT_MINOR = 2 ** 63 - 1


@dataclass(kw_only=True)
class Transfer(
    IdentityMixin,
    TimeActionMixin,
    BaseEntity
):
    """Business operation; status changes alone do not move money.

    PENDING is an execution state. The application must persist the final state
    atomically with ledger entries and balance updates, without committing PENDING.
    """

    sender_wallet_id: UUID
    receiver_wallet_id: UUID
    amount_minor: int
    currency: CurrencyEnum
    status: TransferStatusEnum
    rejection_code: TransferRejectionCodeEnum | None = field(default=None)
    completed_at: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        for value in (self.id, self.sender_wallet_id, self.receiver_wallet_id):
            if not isinstance(value, UUID):
                raise TypeError("Transfer and wallet IDs must be UUIDs")
        if self.sender_wallet_id == self.receiver_wallet_id:
            raise SameWalletTransferError()
        if type(self.amount_minor) is not int or not 0 < self.amount_minor <= MAX_TRANSFER_AMOUNT_MINOR:
            raise InvalidTransferAmountError("Amount must be a positive signed BIGINT")
        if not isinstance(self.currency, CurrencyEnum):
            raise TypeError("Currency must be a CurrencyEnum")
        if not isinstance(self.status, TransferStatusEnum):
            raise TypeError("Status must be a TransferStatusEnum")
        self._require_aware_time(self.created_at)
        self._require_aware_time(self.updated_at)
        if self.updated_at < self.created_at:
            raise InvalidTransferStateError("Update time cannot precede creation")

        if self.status == TransferStatusEnum.COMPLETED:
            self._require_aware_time(self.completed_at)
            if not self.created_at <= self.completed_at <= self.updated_at:
                raise InvalidTransferStateError("Completion time must be between creation and update")
            if self.rejection_code is not None:
                raise InvalidTransferStateError("Completed transfer cannot have a rejection code")
        else:
            if self.completed_at is not None:
                raise InvalidTransferStateError("Only completed transfers may have a completion time")
            if self.status == TransferStatusEnum.REJECTED:
                self._require_rejection_code(self.rejection_code)
            elif self.rejection_code is not None:
                raise InvalidTransferStateError("Pending transfer cannot have a rejection code")

    @classmethod
    def create(
            cls,
            *,
            sender_wallet_id: UUID,
            receiver_wallet_id: UUID,
            amount_minor: int,
            currency: CurrencyEnum,
            now: datetime,
    ) -> Self:
        return cls(
            sender_wallet_id=sender_wallet_id,
            receiver_wallet_id=receiver_wallet_id,
            amount_minor=amount_minor,
            currency=currency,
            status=TransferStatusEnum.PENDING,
            created_at=now,
            updated_at=now,
        )

    def complete(self, now: datetime) -> None:
        self._ensure_pending()
        self._validate_transition_time(now)
        self.status = TransferStatusEnum.COMPLETED
        self.completed_at = now
        self.updated_at = now

    def reject(
            self,
            rejection_code: TransferRejectionCodeEnum,
            *,
            now: datetime,
    ) -> None:
        self._ensure_pending()
        self._require_rejection_code(rejection_code)
        self._validate_transition_time(now)
        self.status = TransferStatusEnum.REJECTED
        self.rejection_code = rejection_code
        self.updated_at = now

    def _ensure_pending(self) -> None:
        if self.status != TransferStatusEnum.PENDING:
            raise TransferNotPendingError()

    def _validate_transition_time(self, now: datetime) -> None:
        self._require_aware_time(now)
        if now < self.updated_at:
            raise InvalidTransferStateError("Transition time cannot precede the last update")

    @staticmethod
    def _require_aware_time(value: datetime) -> None:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise InvalidTransferStateError("Transfer timestamps must be timezone-aware datetimes")

    @staticmethod
    def _require_rejection_code(value: TransferRejectionCodeEnum) -> None:
        if not isinstance(value, TransferRejectionCodeEnum):
            raise InvalidTransferStateError("Rejection code must be a TransferRejectionCodeEnum")

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.application.transfer.dtos.filters import TransferDirectionEnum
from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.enums import TransferRejectionCodeEnum, TransferStatusEnum


@dataclass(frozen=True, kw_only=True)
class TransferDTO:
    id: UUID
    sender_wallet_id: UUID
    receiver_wallet_id: UUID
    amount_minor: int
    currency: CurrencyEnum
    status: TransferStatusEnum
    direction: TransferDirectionEnum
    created_at: datetime
    completed_at: datetime | None
    rejection_code: TransferRejectionCodeEnum | None = None

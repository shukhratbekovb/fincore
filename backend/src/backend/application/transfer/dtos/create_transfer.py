from dataclasses import dataclass
from uuid import UUID

from backend.domain.share.enums import CurrencyEnum


@dataclass(frozen=True)
class CreateTransferCommand:
    user_id: UUID
    sender_wallet_id: UUID
    receiver_wallet_id: UUID
    amount_minor: int
    currency: CurrencyEnum
    idempotency_key: str


@dataclass(frozen=True)
class CreateTransferResult:
    transfer_id: UUID

from dataclasses import dataclass
from uuid import UUID

from backend.domain.share.enums import CurrencyEnum


@dataclass(frozen=True)
class CreateSandboxTopUpCommand:
    user_id: UUID
    wallet_id: UUID
    amount_minor: int
    currency: CurrencyEnum
    idempotency_key: str


@dataclass(frozen=True)
class CreateSandboxTopUpResult:
    top_up_id: UUID

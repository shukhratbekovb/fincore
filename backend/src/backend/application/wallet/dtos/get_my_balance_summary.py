from dataclasses import dataclass
from uuid import UUID

from backend.domain.share.enums import CurrencyEnum


@dataclass(frozen=True)
class GetMyBalanceSummaryCommand:
    user_id: UUID
    currency: CurrencyEnum | None = None

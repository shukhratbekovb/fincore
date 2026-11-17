from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.value_objects import WalletName, WalletNumber


@dataclass(frozen=True, kw_only=True)
class WalletDTO:
    id: UUID
    user_id: UUID
    name: str
    balance_minor: int = field(default=0)
    number: str
    currency: CurrencyEnum
    status: WalletStatusEnum
    created_at: datetime
    updated_at: datetime

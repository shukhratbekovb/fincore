from dataclasses import dataclass
from uuid import UUID

from backend.application.wallet.dtos.filters import WalletFilter


@dataclass(frozen=True)
class GetMyWalletsCommand:
    user_id: UUID
    filters: WalletFilter

from dataclasses import dataclass, field
from uuid import UUID

from backend.application.history.dtos.filters import WalletTransactionFilter


@dataclass(frozen=True)
class GetWalletTransactionsCommand:
    user_id: UUID
    wallet_id: UUID
    filters: WalletTransactionFilter = field(default_factory=WalletTransactionFilter)
    limit: int = 20
    cursor: str | None = None

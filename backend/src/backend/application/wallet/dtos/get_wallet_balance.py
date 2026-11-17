from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetWalletBalanceCommand:
    user_id: UUID
    wallet_id: UUID

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetWalletCommand:
    user_id: UUID
    wallet_id: UUID

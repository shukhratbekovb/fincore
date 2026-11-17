from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class UnfreezeWalletCommand:
    # The authenticated owner is the actor; no administrator override is supported.
    user_id: UUID
    wallet_id: UUID

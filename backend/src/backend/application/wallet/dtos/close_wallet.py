from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CloseWalletCommand:
    # user_id comes from the authenticated context, not the request body.
    user_id: UUID
    wallet_id: UUID

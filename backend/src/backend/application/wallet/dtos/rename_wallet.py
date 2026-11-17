from dataclasses import dataclass
from uuid import UUID

from backend.domain.wallet.value_objects import WalletName


@dataclass(frozen=True)
class RenameWalletCommand:
    # user_id comes from the authenticated context, not the request body.
    user_id: UUID
    wallet_id: UUID
    name: WalletName

from dataclasses import dataclass
from uuid import UUID

from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.value_objects import WalletNumber


@dataclass(frozen=True)
class ResolveWalletRecipientCommand:
    user_id: UUID
    wallet_number: WalletNumber


@dataclass(frozen=True)
class WalletRecipientDTO:
    wallet_id: UUID
    number: str
    currency: CurrencyEnum
    owner: str

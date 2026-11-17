from dataclasses import dataclass, field
from uuid import UUID

from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.value_objects import WalletName


@dataclass(frozen=True)
class CreateWalletCommand:
    # Supplied by the authenticated server context, never from a request body.
    user_id: UUID
    name: WalletName
    currency: CurrencyEnum = field(default=CurrencyEnum.USD)


@dataclass(frozen=True)
class CreateWalletResult:
    wallet_id: UUID

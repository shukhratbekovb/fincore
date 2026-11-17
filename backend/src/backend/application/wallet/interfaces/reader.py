from typing import Protocol
from uuid import UUID

from backend.application.wallet.dtos.base import WalletDTO
from backend.application.wallet.dtos.filters import WalletFilter
from backend.application.wallet.dtos.resolve_recipient import WalletRecipientDTO
from backend.domain.wallet.value_objects import WalletNumber


class IWalletReader(Protocol):
    async def get_recipient_by_number(self, number: WalletNumber) -> WalletRecipientDTO | None: ...

    async def list_by_user_id(
            self,
            user_id: UUID,
            filters: WalletFilter
    ) -> list[WalletDTO]: ...

    async def get_by_id(
            self,
            wallet_id: UUID
    ) -> WalletDTO | None: ...

    async def get_by_id_for_user(
            self,
            wallet_id: UUID,
            *,
            user_id: UUID
    ) -> WalletDTO | None: ...

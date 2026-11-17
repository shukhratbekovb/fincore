from typing import Protocol
from uuid import UUID

from backend.domain.wallet_balance.entities import WalletBalance


class IWalletBalanceRepository(Protocol):
    """Share the UoW transaction; wallet_id is a PK/FK to wallets.id.

    Enforce nonnegative BIGINT amounts/versions in storage. For transfers lock
    balances in ascending wallet ID order and save together with ledger entries.
    """

    async def add(self, balance: WalletBalance) -> None: ...

    async def get_by_wallet_id_for_update(self, wallet_id: UUID) -> WalletBalance | None:
        """Return latest committed state with a row lock until transaction end."""
        ...

    async def save(self, balance: WalletBalance) -> None: ...

from typing import Protocol
from uuid import UUID

from backend.domain.wallet.entities import Wallet


class IWalletRepository(Protocol):
    """Persist in the UoW transaction; wallet numbers must be globally unique.

    Enforce uniqueness in the database and translate number collisions to
    WalletNumberAlreadyExistsError, including conflicts detected at commit.
    Multiple wallets with the same owner/currency remain allowed.
    """

    async def add(self, wallet: Wallet) -> None: ...

    async def get_by_id_for_update(self, wallet_id: UUID) -> Wallet | None:
        """Read latest state with a row lock held until transaction end.

        Wallet operations lock wallets, balances, then ledger accounts. When
        multiple wallets participate, lock each group by ascending wallet ID.
        """
        ...

    async def save(self, wallet: Wallet) -> None: ...

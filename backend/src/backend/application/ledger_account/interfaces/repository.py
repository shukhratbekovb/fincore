from typing import Protocol
from uuid import UUID

from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.share.enums import CurrencyEnum


class ILedgerAccountRepository(Protocol):
    """Share the UoW transaction; never commit independently.

    Enforce unique code, unique (wallet_id, account_type, currency), and wallet FK.
    The account currency must match its wallet currency. Account conflicts must
    not be translated into WalletNumberAlreadyExistsError.
    """

    async def add(self, account: LedgerAccount) -> None: ...

    async def get_by_wallet_id_for_update(self, wallet_id: UUID) -> LedgerAccount | None:
        """Lock the wallet's LIABILITY account until transaction end."""
        ...

    async def save(self, account: LedgerAccount) -> None:
        """Persist status only; accounting identity must remain unchanged."""
        ...

    async def get_sandbox_funding_for_update(self, currency: CurrencyEnum) -> LedgerAccount | None:
        """Lock the pre-provisioned SYS:SIM_FUNDING:{currency} ASSET account.

        Return None when absent; do not create a system account while posting.
        Lock system funding only after all wallet accounts. All posting/closing
        operations must follow this order and share the UoW transaction.
        """
        ...

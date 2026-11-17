from typing import Protocol
from uuid import UUID

from backend.application.history.dtos.base import TransactionDTO, WalletTransactionDTO
from backend.application.history.dtos.filters import MyTransactionsFilter, WalletTransactionFilter
from backend.application.share.dtos.pagination import CursorPosition


class ITransactionHistoryReader(Protocol):
    """Read posted journals and operation projections without writes or locks.

    Mandatory ownership is applied in SQL on every page. Read all wallet statuses,
    exclude unposted/rejected operations, sort (posted_at DESC, journal ID DESC),
    and apply tuple < cursor. Deduplicate journals before LIMIT. Fetch size may
    be 101 for lookahead. Date range is [posted_from, posted_to). No N+1.
    source_type identifies the journal kind, source_id its Transfer/SandboxTopUp.
    No funding account IDs, actor metadata or counterparty balances in the DTO.
    """

    async def list_by_wallet_id_for_user(
            self,
            wallet_id: UUID,
            *,
            user_id: UUID,
            filters: WalletTransactionFilter,
            limit: int,
            cursor: CursorPosition | None,
    ) -> list[WalletTransactionDTO] | None:
        """None for a missing/foreign wallet, [] for its empty history.

        Resolve ownership independently of filters/history presence. Return only
        this wallet's movement. Direction is INCOMING/OUTGOING relative to it;
        for a top-up sender_wallet_id and counterparty_wallet_id are None.
        """
        ...

    async def list_by_user_id(
            self,
            user_id: UUID,
            filters: MyTransactionsFilter,
            *,
            limit: int,
            cursor: CursorPosition | None,
    ) -> list[TransactionDTO]:
        """Sender OR receiver wallet owner = user_id; never override this scope.

        Without wallet filter, a transfer between own wallets is one INTERNAL row.
        With wallet filter, first enforce that wallet's ownership (foreign/missing
        gives []), then direction is relative to it. Top-ups are INCOMING.
        """
        ...

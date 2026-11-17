from typing import Protocol
from uuid import UUID

from backend.application.wallet_balance.dtos.base import BalanceSummaryDTO, WalletBalanceDTO
from backend.domain.share.enums import CurrencyEnum


class IWalletBalanceReader(Protocol):
    """Owner-scoped snapshot projections, without row locks or writes.

    Required balance/LIABILITY account must exist and match the wallet and its
    currency. Corruption raises WalletAccountingStateError, never a zero fallback.
    All wallet statuses are readable. available=posted until holds exist;
    spendable=available only for ACTIVE wallets, otherwise zero.
    as_of is a database read timestamp, not a version or guarantee of consistency
    across separate requests. updated_at belongs to WalletBalance, not Wallet.
    """

    async def get_by_wallet_id_for_user(
            self,
            wallet_id: UUID,
            *,
            user_id: UUID,
    ) -> WalletBalanceDTO | None:
        """None only for missing/foreign wallet, before projection validation.

        For an owned wallet with missing/inconsistent accounting state raise
        WalletAccountingStateError. Return all values from one SQL snapshot.
        """
        ...

    async def get_summary_for_user(
            self,
            user_id: UUID,
            *,
            currency: CurrencyEnum | None,
    ) -> BalanceSummaryDTO:
        """Aggregate ALL owned wallets per currency in one consistent snapshot.

        Include ACTIVE, FROZEN and CLOSED in posted/available totals; count only
        ACTIVE in spendable. Do not derive totals from a paginated wallet list.
        No matching wallets -> totals=[]; a real zero balance remains a currency
        total with zero amounts. Missing account/balance is not an empty result.
        Aggregate sums may exceed a per-wallet BIGINT; do not truncate/cast them
        to BIGINT. Never add different currencies together. Order totals by
        ascending currency code.
        """
        ...

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.application.history.dtos.filters import TransactionDirectionEnum
from backend.domain.ledger_transaction.enums import LedgerTransactionKindEnum
from backend.domain.share.enums import CurrencyEnum


@dataclass(frozen=True, kw_only=True)
class TransactionDTO:
    id: UUID
    source_type: LedgerTransactionKindEnum
    source_id: UUID
    sender_wallet_id: UUID | None
    receiver_wallet_id: UUID
    amount_minor: int
    currency: CurrencyEnum
    direction: TransactionDirectionEnum
    posted_at: datetime


@dataclass(frozen=True, kw_only=True)
class WalletTransactionDTO(TransactionDTO):
    wallet_id: UUID

    @property
    def counterparty_wallet_id(self) -> UUID | None:
        if self.wallet_id == self.sender_wallet_id:
            return self.receiver_wallet_id
        return self.sender_wallet_id

from typing import Protocol

from backend.domain.ledger_transaction.entities import LedgerTransaction


class ILedgerTransactionRepository(Protocol):
    async def add(self, journal: LedgerTransaction) -> None:
        """Append the whole aggregate, including all entries, in the UoW.

        Never commit independently. Enforce unique non-null business source
        links, foreign keys, currencies and journal balancing in persistence.
        Posted journals/entries must not be updated or deleted.
        """
        ...

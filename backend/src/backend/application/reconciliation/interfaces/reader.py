from typing import Protocol

from backend.application.reconciliation.dtos import ReconciliationReport


class ILedgerReconciliationReader(Protocol):
    async def reconcile(self, *, sample_limit: int) -> ReconciliationReport:
        """Inspect one consistent database snapshot without modifying data.

        Counts include every failed check. Examples are bounded per check.
        Currency amounts must use arbitrary-precision integers, never floats.
        """
        ...

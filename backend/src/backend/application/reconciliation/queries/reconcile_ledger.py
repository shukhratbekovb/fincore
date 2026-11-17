from dataclasses import dataclass

from backend.application.reconciliation.dtos import ReconcileLedgerCommand, ReconciliationReport
from backend.application.reconciliation.interfaces.reader import ILedgerReconciliationReader


@dataclass(frozen=True)
class ReconcileLedgerQuery:
    reader: ILedgerReconciliationReader

    async def execute(
            self,
            cmd: ReconcileLedgerCommand,
    ) -> ReconciliationReport:
        if type(cmd.sample_limit) is not int or not 1 <= cmd.sample_limit <= 100:
            raise ValueError("Sample limit must be an integer between 1 and 100")
        return await self.reader.reconcile(sample_limit=cmd.sample_limit)

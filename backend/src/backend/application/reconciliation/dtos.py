from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ReconcileLedgerCommand:
    sample_limit: int = 10


@dataclass(frozen=True)
class ReconciliationExample:
    entity_type: str
    entity_id: UUID
    currency: str | None
    expected_minor: int | None
    actual_minor: int | None


@dataclass(frozen=True)
class ReconciliationFinding:
    code: str
    count: int
    examples: tuple[ReconciliationExample, ...]


@dataclass(frozen=True)
class ReconciliationReport:
    as_of: datetime
    wallets_checked: int
    journals_checked: int
    entries_checked: int
    findings: tuple[ReconciliationFinding, ...]

    @property
    def is_consistent(self) -> bool:
        return not self.findings

    @property
    def issue_count(self) -> int:
        """Number of findings; an entity can fail more than one check."""
        return sum(finding.count for finding in self.findings)

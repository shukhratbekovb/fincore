from dataclasses import dataclass, field
from uuid import UUID

from backend.application.history.dtos.filters import MyTransactionsFilter


@dataclass(frozen=True)
class GetMyTransactionsCommand:
    user_id: UUID
    filters: MyTransactionsFilter = field(default_factory=MyTransactionsFilter)
    limit: int = 20
    cursor: str | None = None

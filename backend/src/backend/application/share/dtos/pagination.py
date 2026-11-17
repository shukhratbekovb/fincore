from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.application.share.errors import InvalidCursorError


@dataclass(frozen=True, kw_only=True)
class PageDTO[T]:
    items: list[T]
    next_cursor: str | None = None


@dataclass(frozen=True, kw_only=True)
class CursorPosition:
    timestamp: datetime
    id: UUID

    def __post_init__(self) -> None:
        if (
            not isinstance(self.timestamp, datetime)
            or self.timestamp.tzinfo is None
            or self.timestamp.utcoffset() is None
            or not isinstance(self.id, UUID)
        ):
            raise InvalidCursorError()

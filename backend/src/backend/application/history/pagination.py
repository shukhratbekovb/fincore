import json
from datetime import timezone
from uuid import UUID

from backend.application.history.dtos.base import TransactionDTO
from backend.application.history.dtos.filters import TransactionFilter
from backend.application.share.dtos.pagination import CursorPosition, PageDTO
from backend.application.share.interfaces.cursor_codec import ICursorCodec


def history_cursor_context(
        *,
        query: str,
        user_id: UUID,
        wallet_id: UUID | None,
        filters: TransactionFilter,
) -> str:
    return json.dumps(
        {
            "query": query,
            "user_id": str(user_id),
            "wallet_id": str(wallet_id) if wallet_id is not None else None,
            "kind": filters.kind.value if filters.kind is not None else None,
            "currency": filters.currency.value if filters.currency is not None else None,
            "direction": filters.direction.value if filters.direction is not None else None,
            "posted_from": filters.posted_from.astimezone(timezone.utc).isoformat() if filters.posted_from is not None else None,
            "posted_to": filters.posted_to.astimezone(timezone.utc).isoformat() if filters.posted_to is not None else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def history_page[T: TransactionDTO](
        rows: list[T],
        *,
        limit: int,
        context: str,
        cursor_codec: ICursorCodec,
) -> PageDTO[T]:
    items = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = cursor_codec.encode(
            CursorPosition(timestamp=last.posted_at, id=last.id),
            context=context,
        )
    return PageDTO(items=items, next_cursor=next_cursor)

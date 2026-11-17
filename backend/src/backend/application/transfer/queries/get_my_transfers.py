import json
from dataclasses import dataclass
from datetime import timezone
from uuid import UUID

from backend.application.auth.errors import UserInactiveError
from backend.application.share.dtos.pagination import CursorPosition, PageDTO
from backend.application.share.errors import InvalidPaginationError
from backend.application.share.interfaces.cursor_codec import ICursorCodec
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.transfer.dtos.base import TransferDTO
from backend.application.transfer.dtos.filters import TransferFilter
from backend.application.transfer.dtos.get_my_transfers import GetMyTransfersCommand
from backend.application.transfer.errors import InvalidTransferFilterError
from backend.application.user.errors import UserNotFoundError


@dataclass(frozen=True)
class GetMyTransfersQuery:
    uow: IUnitOfWork
    cursor_codec: ICursorCodec

    async def execute(
            self,
            cmd: GetMyTransfersCommand
    ) -> PageDTO[TransferDTO]:
        if not isinstance(cmd.user_id, UUID):
            raise TypeError("User ID must be a UUID")
        if not isinstance(cmd.filters, TransferFilter):
            raise InvalidTransferFilterError()
        if type(cmd.limit) is not int or not 1 <= cmd.limit <= 100:
            raise InvalidPaginationError("Limit must be between 1 and 100")

        context = self._cursor_context(cmd)
        async with self.uow:
            user = await self.uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            position = None
            if cmd.cursor is not None:
                position = self.cursor_codec.decode(cmd.cursor, context=context)

            rows = await self.uow.transfer_reader.list_by_user_id(
                user_id=user.id,
                filters=cmd.filters,
                limit=cmd.limit + 1,
                cursor=position,
            )
            items = rows[:cmd.limit]
            next_cursor = None
            if len(rows) > cmd.limit:
                last = items[-1]
                next_cursor = self.cursor_codec.encode(
                    CursorPosition(timestamp=last.created_at, id=last.id),
                    context=context,
                )

            return PageDTO(items=items, next_cursor=next_cursor)

    @staticmethod
    def _cursor_context(cmd: GetMyTransfersCommand) -> str:
        filters = cmd.filters
        return json.dumps(
            {
                "query": "transfer.list",
                "user_id": str(cmd.user_id),
                "wallet_id": str(filters.wallet_id) if filters.wallet_id is not None else None,
                "currency": filters.currency.value if filters.currency is not None else None,
                "status": filters.status.value if filters.status is not None else None,
                "direction": filters.direction.value if filters.direction is not None else None,
                "created_from": filters.created_from.astimezone(timezone.utc).isoformat() if filters.created_from is not None else None,
                "created_to": filters.created_to.astimezone(timezone.utc).isoformat() if filters.created_to is not None else None,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

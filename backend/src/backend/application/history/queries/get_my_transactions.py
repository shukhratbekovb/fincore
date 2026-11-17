from dataclasses import dataclass
from uuid import UUID

from backend.application.auth.errors import UserInactiveError
from backend.application.history.dtos.base import TransactionDTO
from backend.application.history.dtos.filters import MyTransactionsFilter
from backend.application.history.dtos.get_my_transactions import GetMyTransactionsCommand
from backend.application.history.errors import InvalidTransactionFilterError
from backend.application.history.pagination import history_cursor_context, history_page
from backend.application.share.dtos.pagination import PageDTO
from backend.application.share.errors import InvalidPaginationError
from backend.application.share.interfaces.cursor_codec import ICursorCodec
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError


@dataclass(frozen=True)
class GetMyTransactionsQuery:
    uow: IUnitOfWork
    cursor_codec: ICursorCodec

    async def execute(
            self,
            cmd: GetMyTransactionsCommand
    ) -> PageDTO[TransactionDTO]:
        if not isinstance(cmd.user_id, UUID):
            raise TypeError("User ID must be a UUID")
        if not isinstance(cmd.filters, MyTransactionsFilter):
            raise InvalidTransactionFilterError()
        if type(cmd.limit) is not int or not 1 <= cmd.limit <= 100:
            raise InvalidPaginationError("Limit must be between 1 and 100")

        context = history_cursor_context(
            query="history.user",
            user_id=cmd.user_id,
            wallet_id=cmd.filters.wallet_id,
            filters=cmd.filters,
        )
        async with self.uow:
            user = await self.uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            position = self.cursor_codec.decode(cmd.cursor, context=context) if cmd.cursor is not None else None
            rows = await self.uow.transaction_history_reader.list_by_user_id(
                user_id=user.id,
                filters=cmd.filters,
                limit=cmd.limit + 1,
                cursor=position,
            )
            return history_page(rows, limit=cmd.limit, context=context, cursor_codec=self.cursor_codec)

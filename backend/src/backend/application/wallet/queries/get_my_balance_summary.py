from dataclasses import dataclass
from uuid import UUID

from backend.application.auth.errors import UserInactiveError
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.get_my_balance_summary import GetMyBalanceSummaryCommand
from backend.application.wallet_balance.dtos.base import BalanceSummaryDTO
from backend.domain.share.enums import CurrencyEnum


@dataclass(frozen=True)
class GetMyBalanceSummaryQuery:
    uow: IUnitOfWork

    async def execute(
            self,
            cmd: GetMyBalanceSummaryCommand
    ) -> BalanceSummaryDTO:
        if not isinstance(cmd.user_id, UUID):
            raise TypeError("User ID must be a UUID")
        if cmd.currency is not None and not isinstance(cmd.currency, CurrencyEnum):
            raise TypeError("Currency must be a CurrencyEnum")

        async with self.uow:
            user = await self.uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            return await self.uow.wallet_balance_reader.get_summary_for_user(
                user_id=user.id,
                currency=cmd.currency,
            )

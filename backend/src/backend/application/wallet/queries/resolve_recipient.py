from dataclasses import dataclass

from backend.application.auth.errors import UserInactiveError
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.resolve_recipient import ResolveWalletRecipientCommand, WalletRecipientDTO
from backend.application.wallet.errors import WalletNotFoundError


@dataclass(frozen=True)
class ResolveWalletRecipientQuery:
    uow: IUnitOfWork

    async def execute(self, cmd: ResolveWalletRecipientCommand) -> WalletRecipientDTO:
        async with self.uow:
            user = await self.uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            recipient = await self.uow.wallet_reader.get_recipient_by_number(cmd.wallet_number)
            if recipient is None:
                raise WalletNotFoundError()
            return recipient

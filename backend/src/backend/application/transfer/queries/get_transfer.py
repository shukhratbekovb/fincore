from dataclasses import dataclass
from uuid import UUID

from backend.application.auth.errors import UserInactiveError
from backend.application.share.interfaces.uow import IUnitOfWork
from backend.application.transfer.dtos.base import TransferDTO
from backend.application.transfer.dtos.get_transfer import GetTransferCommand
from backend.application.transfer.errors import TransferNotFoundError
from backend.application.user.errors import UserNotFoundError


@dataclass(frozen=True)
class GetTransferQuery:
    uow: IUnitOfWork

    async def execute(
            self,
            cmd: GetTransferCommand
    ) -> TransferDTO:
        if not isinstance(cmd.user_id, UUID) or not isinstance(cmd.transfer_id, UUID):
            raise TypeError("User and transfer IDs must be UUIDs")

        async with self.uow:
            user = await self.uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise UserNotFoundError()
            if not user.is_active():
                raise UserInactiveError()

            transfer = await self.uow.transfer_reader.get_by_id_for_user(
                cmd.transfer_id,
                user_id=user.id,
            )
            if transfer is None:
                raise TransferNotFoundError()

            return transfer

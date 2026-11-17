from uuid import UUID

from sqlalchemy import select, and_, or_, tuple_
from sqlalchemy.orm import aliased

from backend.application.share.dtos.pagination import CursorPosition
from backend.application.transfer.dtos.base import TransferDTO
from backend.application.transfer.dtos.filters import TransferFilter, TransferDirectionEnum
from backend.application.transfer.interfaces.reader import ITransferReader
from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.enums import TransferStatusEnum, TransferRejectionCodeEnum
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyTransferModel, SqlAlchemyWalletModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_dto(row, user_id: UUID) -> TransferDTO:
    outgoing = row['sender_owner_id'] == user_id
    incoming = row['receiver_owner_id'] == user_id
    direction = TransferDirectionEnum.INTERNAL if outgoing and incoming else TransferDirectionEnum.OUTGOING if outgoing else TransferDirectionEnum.INCOMING
    return TransferDTO(
        id=row['id'], sender_wallet_id=row['sender_wallet_id'], receiver_wallet_id=row['receiver_wallet_id'],
        amount_minor=row['amount_minor'], currency=CurrencyEnum(row['currency']), status=TransferStatusEnum(row['status']),
        direction=direction, created_at=row['created_at'], completed_at=row['completed_at'],
        rejection_code=TransferRejectionCodeEnum(row['rejection_code']) if row['rejection_code'] is not None else None,
    )


class SqlAlchemyTransferReader(ITransferReader, SqlAlchemyBaseRepository):
    def _base_stmt(self, user_id: UUID):
        sender = aliased(SqlAlchemyWalletModel)
        receiver = aliased(SqlAlchemyWalletModel)
        stmt = select(
            *SqlAlchemyTransferModel.__table__.c,
            sender.user_id.label('sender_owner_id'), receiver.user_id.label('receiver_owner_id'),
        ).join(sender, sender.id == SqlAlchemyTransferModel.sender_wallet_id).join(
            receiver, receiver.id == SqlAlchemyTransferModel.receiver_wallet_id,
        ).where(or_(sender.user_id == user_id, receiver.user_id == user_id))
        return stmt, sender, receiver

    async def get_by_id_for_user(self, transfer_id: UUID, *, user_id: UUID) -> TransferDTO | None:
        stmt, _, _ = self._base_stmt(user_id)
        result = await self.session.execute(stmt.where(SqlAlchemyTransferModel.id == transfer_id))
        row = result.mappings().one_or_none()
        return _to_dto(row, user_id) if row is not None else None

    async def list_by_user_id(self, user_id: UUID, filters: TransferFilter, *, limit: int, cursor: CursorPosition | None) -> list[TransferDTO]:
        stmt, sender, receiver = self._base_stmt(user_id)
        if filters.wallet_id is not None:
            stmt = stmt.where(or_(
                and_(sender.id == filters.wallet_id, sender.user_id == user_id),
                and_(receiver.id == filters.wallet_id, receiver.user_id == user_id),
            ))
        if filters.currency is not None:
            stmt = stmt.where(SqlAlchemyTransferModel.currency == filters.currency.value)
        if filters.status is not None:
            stmt = stmt.where(SqlAlchemyTransferModel.status == filters.status.value)
        if filters.direction == TransferDirectionEnum.INTERNAL:
            stmt = stmt.where(sender.user_id == user_id, receiver.user_id == user_id)
        elif filters.direction == TransferDirectionEnum.OUTGOING:
            stmt = stmt.where(sender.user_id == user_id, receiver.user_id != user_id)
        elif filters.direction == TransferDirectionEnum.INCOMING:
            stmt = stmt.where(receiver.user_id == user_id, sender.user_id != user_id)
        if filters.created_from is not None:
            stmt = stmt.where(SqlAlchemyTransferModel.created_at >= filters.created_from)
        if filters.created_to is not None:
            stmt = stmt.where(SqlAlchemyTransferModel.created_at < filters.created_to)
        if cursor is not None:
            stmt = stmt.where(tuple_(SqlAlchemyTransferModel.created_at, SqlAlchemyTransferModel.id) < tuple_(cursor.timestamp, cursor.id))
        stmt = stmt.order_by(SqlAlchemyTransferModel.created_at.desc(), SqlAlchemyTransferModel.id.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return [_to_dto(row, user_id) for row in result.mappings().all()]

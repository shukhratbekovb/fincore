from uuid import UUID

from sqlalchemy import select, func, case, and_, or_, tuple_
from sqlalchemy.orm import aliased

from backend.application.history.dtos.base import TransactionDTO, WalletTransactionDTO
from backend.application.history.dtos.filters import MyTransactionsFilter, WalletTransactionFilter, TransactionDirectionEnum
from backend.application.history.interfaces.reader import ITransactionHistoryReader
from backend.application.share.dtos.pagination import CursorPosition
from backend.domain.ledger_transaction.enums import LedgerTransactionKindEnum
from backend.domain.share.enums import CurrencyEnum
from backend.infrastructure.db.sqlalchemy.models import (
    SqlAlchemyWalletModel, SqlAlchemyTransferModel, SqlAlchemySandboxTopUpModel, SqlAlchemyLedgerTransactionModel,
)
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_dto(row) -> TransactionDTO:
    return TransactionDTO(
        id=row['id'], source_type=LedgerTransactionKindEnum(row['kind']), source_id=row['source_id'],
        sender_wallet_id=row['sender_wallet_id'], receiver_wallet_id=row['receiver_wallet_id'],
        amount_minor=row['amount_minor'], currency=CurrencyEnum(row['currency']),
        direction=TransactionDirectionEnum(row['direction']), posted_at=row['posted_at'],
    )


class SqlAlchemyTransactionHistoryReader(ITransactionHistoryReader, SqlAlchemyBaseRepository):
    def _base_stmt(self, user_id: UUID, wallet_id: UUID | None):
        sender = aliased(SqlAlchemyWalletModel)
        receiver = aliased(SqlAlchemyWalletModel)
        receiver_id = func.coalesce(SqlAlchemyTransferModel.receiver_wallet_id, SqlAlchemySandboxTopUpModel.wallet_id)
        if wallet_id is not None:
            direction = case((receiver_id == wallet_id, 'incoming'), else_='outgoing')
        else:
            direction = case(
                (and_(sender.user_id == user_id, receiver.user_id == user_id), 'internal'),
                (receiver.user_id == user_id, 'incoming'), else_='outgoing',
            )
        stmt = select(
            SqlAlchemyLedgerTransactionModel.id, SqlAlchemyLedgerTransactionModel.kind,
            SqlAlchemyLedgerTransactionModel.currency, SqlAlchemyLedgerTransactionModel.posted_at,
            func.coalesce(SqlAlchemyLedgerTransactionModel.transfer_id, SqlAlchemyLedgerTransactionModel.sandbox_top_up_id).label('source_id'),
            SqlAlchemyTransferModel.sender_wallet_id,
            receiver_id.label('receiver_wallet_id'),
            func.coalesce(SqlAlchemyTransferModel.amount_minor, SqlAlchemySandboxTopUpModel.amount_minor).label('amount_minor'),
            direction.label('direction'),
        ).outerjoin(SqlAlchemyTransferModel, SqlAlchemyTransferModel.id == SqlAlchemyLedgerTransactionModel.transfer_id).outerjoin(
            SqlAlchemySandboxTopUpModel, SqlAlchemySandboxTopUpModel.id == SqlAlchemyLedgerTransactionModel.sandbox_top_up_id,
        ).outerjoin(sender, sender.id == SqlAlchemyTransferModel.sender_wallet_id).join(receiver, receiver.id == receiver_id).where(
            or_(sender.user_id == user_id, receiver.user_id == user_id),
            or_(SqlAlchemyTransferModel.status == 'completed', SqlAlchemySandboxTopUpModel.status == 'completed'),
        )
        if wallet_id is not None:
            stmt = stmt.where(or_(
                and_(sender.id == wallet_id, sender.user_id == user_id),
                and_(receiver.id == wallet_id, receiver.user_id == user_id),
            ))
        return stmt, direction

    def _filtered(self, stmt, direction, filters, limit: int, cursor: CursorPosition | None):
        if filters.kind is not None:
            stmt = stmt.where(SqlAlchemyLedgerTransactionModel.kind == filters.kind.value)
        if filters.currency is not None:
            stmt = stmt.where(SqlAlchemyLedgerTransactionModel.currency == filters.currency.value)
        if filters.direction is not None:
            stmt = stmt.where(direction == filters.direction.value)
        if filters.posted_from is not None:
            stmt = stmt.where(SqlAlchemyLedgerTransactionModel.posted_at >= filters.posted_from)
        if filters.posted_to is not None:
            stmt = stmt.where(SqlAlchemyLedgerTransactionModel.posted_at < filters.posted_to)
        if cursor is not None:
            stmt = stmt.where(tuple_(SqlAlchemyLedgerTransactionModel.posted_at, SqlAlchemyLedgerTransactionModel.id) < tuple_(cursor.timestamp, cursor.id))
        return stmt.order_by(SqlAlchemyLedgerTransactionModel.posted_at.desc(), SqlAlchemyLedgerTransactionModel.id.desc()).limit(limit)

    async def list_by_wallet_id_for_user(self, wallet_id: UUID, *, user_id: UUID, filters: WalletTransactionFilter, limit: int, cursor: CursorPosition | None) -> list[WalletTransactionDTO] | None:
        result = await self.session.execute(select(SqlAlchemyWalletModel.id).where(
            SqlAlchemyWalletModel.id == wallet_id, SqlAlchemyWalletModel.user_id == user_id,
        ))
        if result.scalar_one_or_none() is None:
            return None
        stmt, direction = self._base_stmt(user_id, wallet_id)
        result = await self.session.execute(self._filtered(stmt, direction, filters, limit, cursor))
        return [WalletTransactionDTO(**vars(_to_dto(row)), wallet_id=wallet_id) for row in result.mappings().all()]

    async def list_by_user_id(self, user_id: UUID, filters: MyTransactionsFilter, *, limit: int, cursor: CursorPosition | None) -> list[TransactionDTO]:
        stmt, direction = self._base_stmt(user_id, filters.wallet_id)
        result = await self.session.execute(self._filtered(stmt, direction, filters, limit, cursor))
        return [_to_dto(row) for row in result.mappings().all()]

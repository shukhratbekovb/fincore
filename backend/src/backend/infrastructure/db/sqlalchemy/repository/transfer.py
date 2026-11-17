from backend.application.transfer.interfaces.repository import ITransferRepository
from backend.domain.transfer.entities import Transfer
from backend.domain.transfer.enums import TransferStatusEnum, TransferRejectionCodeEnum
from backend.domain.share.enums import CurrencyEnum
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyTransferModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_entity(
        model: SqlAlchemyTransferModel
) -> Transfer:
    return Transfer(
        id=model.id,
        sender_wallet_id=model.sender_wallet_id,
        receiver_wallet_id=model.receiver_wallet_id,
        amount_minor=model.amount_minor,
        currency=CurrencyEnum(model.currency),
        status=TransferStatusEnum(model.status),
        rejection_code=TransferRejectionCodeEnum(model.rejection_code) if model.rejection_code is not None else None,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


def _to_model(
        entity: Transfer
) -> SqlAlchemyTransferModel:
    return SqlAlchemyTransferModel(
        id=entity.id,
        sender_wallet_id=entity.sender_wallet_id,
        receiver_wallet_id=entity.receiver_wallet_id,
        amount_minor=entity.amount_minor,
        currency=entity.currency.value,
        status=entity.status.value,
        rejection_code=entity.rejection_code.value if entity.rejection_code is not None else None,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        completed_at=entity.completed_at,
    )


class SqlAlchemyTransferRepository(
    ITransferRepository,
    SqlAlchemyBaseRepository
):
    async def add(self, transfer: Transfer) -> None:
        model = _to_model(transfer)
        self.session.add(model)
        await self.session.flush()

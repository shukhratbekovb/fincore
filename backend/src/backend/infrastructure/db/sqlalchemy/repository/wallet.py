from uuid import UUID

from sqlalchemy import select, update

from backend.application.share.errors import EntityNotFoundError
from backend.application.wallet.interfaces.repository import IWalletRepository
from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.value_objects import WalletName, WalletNumber
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyWalletModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_entity(
        model: SqlAlchemyWalletModel
) -> Wallet:
    return Wallet(
        id=model.id,
        user_id=model.user_id,
        name=WalletName(model.name),
        number=WalletNumber(model.number),
        currency=CurrencyEnum(model.currency),
        status=WalletStatusEnum(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at
    )


def _to_model(
        entity: Wallet
) -> SqlAlchemyWalletModel:
    return SqlAlchemyWalletModel(
        id=entity.id,
        user_id=entity.user_id,
        name=entity.name.value,
        number=entity.number.value,
        currency=entity.currency.value,
        status=entity.status.value,
        created_at=entity.created_at,
        updated_at=entity.updated_at
    )


class SqlAlchemyWalletRepository(
    IWalletRepository,
    SqlAlchemyBaseRepository
):

    async def add(self, wallet: Wallet) -> None:
        model = _to_model(wallet)
        self.session.add(model)
        await self.session.flush()

    async def get_by_id_for_update(self, wallet_id: UUID) -> Wallet | None:
        stmt = (
            select(SqlAlchemyWalletModel)
            .where(SqlAlchemyWalletModel.id == wallet_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        wallet = result.scalar_one_or_none()
        return _to_entity(wallet) if wallet else None

    async def save(self, wallet: Wallet) -> None:
        stmt = (
            update(SqlAlchemyWalletModel)
            .where(SqlAlchemyWalletModel.id == wallet.id)
            .values(
                name=wallet.name.value,
                status=wallet.status.value,
                updated_at=wallet.updated_at,
            )
            .returning(SqlAlchemyWalletModel.id)
        )

        result = await self.session.execute(stmt)

        if result.scalar_one_or_none() is None:
            raise EntityNotFoundError("wallets record not found")

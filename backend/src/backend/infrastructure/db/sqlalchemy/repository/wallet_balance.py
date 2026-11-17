from uuid import UUID

from sqlalchemy import select, update

from backend.application.share.errors import EntityNotFoundError
from backend.application.wallet_balance.interfaces.repository import IWalletBalanceRepository
from backend.domain.wallet_balance.entities import WalletBalance
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyWalletBalanceModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_entity(
        model: SqlAlchemyWalletBalanceModel
) -> WalletBalance:
    return WalletBalance(
        wallet_id=model.wallet_id,
        posted_minor=model.posted_minor,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at
    )


def _to_model(
        entity: WalletBalance
) -> SqlAlchemyWalletBalanceModel:
    return SqlAlchemyWalletBalanceModel(
        wallet_id=entity.wallet_id,
        posted_minor=entity.posted_minor,
        version=entity.version,
        created_at=entity.created_at,
        updated_at=entity.updated_at
    )


class SqlAlchemyWalletBalanceRepository(
    IWalletBalanceRepository,
    SqlAlchemyBaseRepository
):

    async def add(self, balance: WalletBalance) -> None:
        model = _to_model(balance)
        self.session.add(model)
        await self.session.flush()

    async def get_by_wallet_id_for_update(self, wallet_id: UUID) -> WalletBalance | None:
        stmt = (
            select(SqlAlchemyWalletBalanceModel)
            .where(SqlAlchemyWalletBalanceModel.wallet_id == wallet_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        balance = result.scalar_one_or_none()
        return _to_entity(balance) if balance else None

    async def save(self, balance: WalletBalance) -> None:
        stmt = (
            update(SqlAlchemyWalletBalanceModel)
            .where(SqlAlchemyWalletBalanceModel.wallet_id == balance.wallet_id)
            .values(
                posted_minor=balance.posted_minor,
                version=balance.version,
                updated_at=balance.updated_at,
            )
            .returning(SqlAlchemyWalletBalanceModel.wallet_id)
        )

        result = await self.session.execute(stmt)

        if result.scalar_one_or_none() is None:
            raise EntityNotFoundError("wallet_balances record not found")

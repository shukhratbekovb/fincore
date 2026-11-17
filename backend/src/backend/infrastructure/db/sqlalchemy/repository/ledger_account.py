from uuid import UUID

from sqlalchemy import select, update

from backend.application.share.errors import EntityNotFoundError
from backend.application.ledger_account.interfaces.repository import ILedgerAccountRepository
from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_account.enums import AccountStatus, AccountType
from backend.domain.ledger_account.value_objects import LedgerAccountCode
from backend.domain.share.enums import CurrencyEnum
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyLedgerAccountModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_entity(
        model: SqlAlchemyLedgerAccountModel
) -> LedgerAccount:
    return LedgerAccount(
        id=model.id,
        code=LedgerAccountCode(model.code),
        account_type=AccountType(model.account_type),
        currency=CurrencyEnum(model.currency),
        created_at=model.created_at,
        wallet_id=model.wallet_id,
        status=AccountStatus(model.status)
    )


def _to_model(
        entity: LedgerAccount
) -> SqlAlchemyLedgerAccountModel:
    return SqlAlchemyLedgerAccountModel(
        id=entity.id,
        code=entity.code.value,
        account_type=entity.account_type.value,
        currency=entity.currency.value,
        created_at=entity.created_at,
        wallet_id=entity.wallet_id,
        status=entity.status.value
    )


class SqlAlchemyLedgerAccountRepository(
    ILedgerAccountRepository,
    SqlAlchemyBaseRepository
):

    async def add(self, account: LedgerAccount) -> None:
        model = _to_model(account)
        self.session.add(model)
        await self.session.flush()

    async def get_by_wallet_id_for_update(self, wallet_id: UUID) -> LedgerAccount | None:
        stmt = (
            select(SqlAlchemyLedgerAccountModel)
            .where(SqlAlchemyLedgerAccountModel.wallet_id == wallet_id, SqlAlchemyLedgerAccountModel.account_type == AccountType.LIABILITY.value)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        account = result.scalar_one_or_none()
        return _to_entity(account) if account else None

    async def save(self, account: LedgerAccount) -> None:
        stmt = (
            update(SqlAlchemyLedgerAccountModel)
            .where(SqlAlchemyLedgerAccountModel.id == account.id)
            .values(
                status=account.status.value,
            )
            .returning(SqlAlchemyLedgerAccountModel.id)
        )

        result = await self.session.execute(stmt)

        if result.scalar_one_or_none() is None:
            raise EntityNotFoundError("ledger_accounts record not found")

    async def get_sandbox_funding_for_update(self, currency: CurrencyEnum) -> LedgerAccount | None:
        stmt = select(SqlAlchemyLedgerAccountModel).where(
            SqlAlchemyLedgerAccountModel.code == f"SYS:SIM_FUNDING:{currency.value}",
            SqlAlchemyLedgerAccountModel.currency == currency.value,
            SqlAlchemyLedgerAccountModel.wallet_id.is_(None),
        ).with_for_update().execution_options(populate_existing=True)
        result = await self.session.execute(stmt)
        account = result.scalar_one_or_none()
        return _to_entity(account) if account else None

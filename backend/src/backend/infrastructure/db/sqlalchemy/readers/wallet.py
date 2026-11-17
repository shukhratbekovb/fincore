from sqlalchemy import select, RowMapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.wallet.dtos.base import WalletDTO
from backend.application.wallet.dtos.filters import WalletFilter, WalletSortEnum
from backend.application.wallet.errors import WalletAccountingStateError
from backend.application.wallet.interfaces.reader import IWalletReader
from backend.application.wallet.dtos.resolve_recipient import WalletRecipientDTO
from backend.domain.user.enums import UserStatusEnum
from backend.domain.wallet.value_objects import WalletNumber
from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.enums import WalletStatusEnum
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyWalletModel, SqlAlchemyWalletBalanceModel, SqlAlchemyUserModel

_SORT_COLUMNS = {
    WalletSortEnum.name_asc: SqlAlchemyWalletModel.name.asc(),
    WalletSortEnum.name_desc: SqlAlchemyWalletModel.name.desc(),
    WalletSortEnum.currency_asc: SqlAlchemyWalletModel.currency.asc(),
    WalletSortEnum.currency_desc: SqlAlchemyWalletModel.currency.desc(),
    WalletSortEnum.created_at_asc: SqlAlchemyWalletModel.created_at.asc(),
    WalletSortEnum.created_at_desc: SqlAlchemyWalletModel.created_at.desc(),
    WalletSortEnum.status_asc: SqlAlchemyWalletModel.status.asc(),
    WalletSortEnum.status_desc: SqlAlchemyWalletModel.status.desc(),
    WalletSortEnum.balance_asc: SqlAlchemyWalletBalanceModel.posted_minor.asc(),
    WalletSortEnum.balance_desc: SqlAlchemyWalletBalanceModel.posted_minor.desc()
}


class SqlAlchemyWalletReader(IWalletReader):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_recipient_by_number(self, number: WalletNumber) -> WalletRecipientDTO | None:
        stmt = select(
            SqlAlchemyWalletModel.id.label('wallet_id'),
            SqlAlchemyWalletModel.number,
            SqlAlchemyWalletModel.currency,
            SqlAlchemyUserModel.username.label('owner'),
        ).join(
            SqlAlchemyUserModel, SqlAlchemyUserModel.id == SqlAlchemyWalletModel.user_id,
        ).where(
            SqlAlchemyWalletModel.number == number.value,
            SqlAlchemyWalletModel.status == WalletStatusEnum.ACTIVE,
            SqlAlchemyUserModel.status == UserStatusEnum.ACTIVE,
        )
        result = await self.session.execute(stmt)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return WalletRecipientDTO(
            wallet_id=row['wallet_id'], number=row['number'],
            currency=CurrencyEnum(row['currency']), owner=row['owner'],
        )

    def _base_stmt(
            self
    ):
        return select(
            SqlAlchemyWalletModel.id,
            SqlAlchemyWalletModel.user_id,
            SqlAlchemyWalletModel.name,
            SqlAlchemyWalletBalanceModel.posted_minor.label("balance_minor"),
            SqlAlchemyWalletModel.number,
            SqlAlchemyWalletModel.currency,
            SqlAlchemyWalletModel.status,
            SqlAlchemyWalletModel.created_at,
            SqlAlchemyWalletModel.updated_at
        ).outerjoin(
            SqlAlchemyWalletBalanceModel,
            SqlAlchemyWalletBalanceModel.wallet_id == SqlAlchemyWalletModel.id
        )

    def _to_dto(
            self,
            row: RowMapping
    ):

        if row["balance_minor"] is None:
            raise WalletAccountingStateError()

        return WalletDTO(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            balance_minor=row["balance_minor"],
            number=row["number"],
            currency=CurrencyEnum(row["currency"]),
            status=WalletStatusEnum(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )

    async def get_by_id(
            self,
            wallet_id: UUID
    ) -> WalletDTO | None:
        stmt = self._base_stmt().where(SqlAlchemyWalletModel.id == wallet_id)
        result = await self.session.execute(stmt)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return self._to_dto(row)

    async def list_by_user_id(
            self,
            user_id: UUID,
            filters: WalletFilter
    ) -> list[WalletDTO]:
        stmt = self._base_stmt().where(SqlAlchemyWalletModel.user_id == user_id)

        if filters.currency is not None:
            stmt = stmt.where(SqlAlchemyWalletModel.currency == filters.currency)

        if filters.status is not None:
            stmt = stmt.where(SqlAlchemyWalletModel.status == filters.status)

        sort_column = _SORT_COLUMNS[
            filters.sort_by if filters.sort_by is not None else WalletSortEnum.created_at_asc
        ]
        stmt = stmt.order_by(sort_column, SqlAlchemyWalletModel.id.asc())

        result = await self.session.execute(stmt)
        rows = result.mappings().all()
        return [self._to_dto(row) for row in rows]

    async def get_by_id_for_user(
            self,
            wallet_id: UUID,
            *,
            user_id: UUID
    ) -> WalletDTO | None:
        stmt = self._base_stmt().where(
            SqlAlchemyWalletModel.id == wallet_id,
            SqlAlchemyWalletModel.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return self._to_dto(row)

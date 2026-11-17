from uuid import UUID

from sqlalchemy import select, func, case, or_, and_, literal, true

from backend.application.wallet.errors import WalletAccountingStateError
from backend.application.wallet_balance.dtos.base import BalanceSummaryDTO, CurrencyBalanceDTO, WalletBalanceDTO
from backend.application.wallet_balance.interfaces.reader import IWalletBalanceReader
from backend.domain.share.enums import CurrencyEnum
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyWalletModel, SqlAlchemyWalletBalanceModel, SqlAlchemyLedgerAccountModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _invalid_projection():
    return or_(
        SqlAlchemyWalletBalanceModel.wallet_id.is_(None), SqlAlchemyLedgerAccountModel.id.is_(None),
        SqlAlchemyLedgerAccountModel.currency != SqlAlchemyWalletModel.currency,
        SqlAlchemyLedgerAccountModel.account_type != 'liability',
        and_(SqlAlchemyWalletModel.status == 'closed', SqlAlchemyLedgerAccountModel.status != 'closed'),
        and_(SqlAlchemyWalletModel.status != 'closed', SqlAlchemyLedgerAccountModel.status != 'active'),
    )


def _joined(stmt):
    return stmt.select_from(SqlAlchemyWalletModel).outerjoin(
        SqlAlchemyWalletBalanceModel, SqlAlchemyWalletBalanceModel.wallet_id == SqlAlchemyWalletModel.id,
    ).outerjoin(SqlAlchemyLedgerAccountModel, SqlAlchemyLedgerAccountModel.wallet_id == SqlAlchemyWalletModel.id)


def _to_dto(row) -> WalletBalanceDTO:
    if row['invalid']:
        raise WalletAccountingStateError()
    return WalletBalanceDTO(
        wallet_id=row['wallet_id'], currency=CurrencyEnum(row['currency']),
        posted_minor=row['posted_minor'], available_minor=row['posted_minor'],
        spendable_minor=row['posted_minor'] if row['status'] == 'active' else 0,
        version=row['version'], updated_at=row['updated_at'], as_of=row['as_of'],
    )


class SqlAlchemyWalletBalanceReader(IWalletBalanceReader, SqlAlchemyBaseRepository):
    async def get_by_wallet_id_for_user(self, wallet_id: UUID, *, user_id: UUID) -> WalletBalanceDTO | None:
        stmt = _joined(select(
            SqlAlchemyWalletModel.id.label('wallet_id'), SqlAlchemyWalletModel.currency, SqlAlchemyWalletModel.status,
            SqlAlchemyWalletBalanceModel.posted_minor, SqlAlchemyWalletBalanceModel.version,
            SqlAlchemyWalletBalanceModel.updated_at, func.statement_timestamp().label('as_of'),
            _invalid_projection().label('invalid'),
        )).where(SqlAlchemyWalletModel.id == wallet_id, SqlAlchemyWalletModel.user_id == user_id)
        result = await self.session.execute(stmt)
        row = result.mappings().one_or_none()
        return _to_dto(row) if row is not None else None

    async def get_summary_for_user(self, user_id: UUID, *, currency: CurrencyEnum | None) -> BalanceSummaryDTO:
        stmt = _joined(select(
            SqlAlchemyWalletModel.currency,
            func.sum(SqlAlchemyWalletBalanceModel.posted_minor).label('posted_minor'),
            func.sum(case((SqlAlchemyWalletModel.status == 'active', SqlAlchemyWalletBalanceModel.posted_minor), else_=0)).label('spendable_minor'),
            func.bool_or(_invalid_projection()).label('invalid'),
        )).where(SqlAlchemyWalletModel.user_id == user_id)
        if currency is not None:
            stmt = stmt.where(SqlAlchemyWalletModel.currency == currency.value)
        totals = stmt.group_by(SqlAlchemyWalletModel.currency).cte('currency_totals')
        singleton = select(literal(1)).subquery()
        stmt = select(totals, func.statement_timestamp().label('as_of')).select_from(
            singleton.outerjoin(totals, true()),
        ).order_by(totals.c.currency)
        result = await self.session.execute(stmt)
        rows = result.mappings().all()
        values = []
        for row in rows:
            if row['invalid']:
                raise WalletAccountingStateError()
            if row['currency'] is not None:
                values.append(CurrencyBalanceDTO(
                    currency=CurrencyEnum(row['currency']), posted_minor=int(row['posted_minor']),
                    available_minor=int(row['posted_minor']), spendable_minor=int(row['spendable_minor']),
                ))
        return BalanceSummaryDTO(totals=values, as_of=rows[0]['as_of'])

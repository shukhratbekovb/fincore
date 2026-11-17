import argparse
import asyncio
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.share.enums import CurrencyEnum
from backend.infrastructure.clock import SystemClock
from backend.infrastructure.db.sqlalchemy.core.database import create_engine, create_session_factory
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemySandboxOperatorModel
from backend.infrastructure.settings import get_settings


async def configure_operator(user_id: UUID, *, revoke: bool = False) -> None:
    engine = create_engine(get_settings())
    try:
        async with SqlAlchemyUnitOfWork(create_session_factory(engine)) as uow:
            user = await uow.users.get_by_id_for_update(user_id)
            if user is None:
                raise ValueError("Operator user does not exist")
            if revoke:
                await uow.session.execute(delete(SqlAlchemySandboxOperatorModel).where(SqlAlchemySandboxOperatorModel.user_id == user_id))
            else:
                if not user.is_active():
                    raise ValueError("Operator must be active")
                await uow.session.execute(insert(SqlAlchemySandboxOperatorModel).values(user_id=user_id).on_conflict_do_nothing())
                for currency in CurrencyEnum:
                    if await uow.ledger_accounts.get_sandbox_funding_for_update(currency) is None:
                        await uow.ledger_accounts.add(LedgerAccount.for_sandbox_funding(currency=currency, now=SystemClock().now()))
            await uow.commit()
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant/revoke server-managed sandbox funding permission")
    parser.add_argument('--operator-user-id', required=True, type=UUID)
    parser.add_argument('--revoke', action='store_true')
    args = parser.parse_args()
    asyncio.run(configure_operator(args.operator_user_id, revoke=args.revoke))
    print('Sandbox operator configuration saved. SANDBOX_ENABLED is controlled separately.')


if __name__ == '__main__':
    main()

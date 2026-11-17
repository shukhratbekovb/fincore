from backend.application.sandbox_top_up.interfaces.repository import ISandboxTopUpRepository
from backend.domain.sandbox_top_up.entities import SandboxTopUp
from backend.domain.sandbox_top_up.enums import SandboxTopUpStatusEnum, SandboxTopUpRejectionCodeEnum
from backend.domain.share.enums import CurrencyEnum
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemySandboxTopUpModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_entity(
        model: SqlAlchemySandboxTopUpModel
) -> SandboxTopUp:
    return SandboxTopUp(
        id=model.id,
        wallet_id=model.wallet_id,
        initiated_by_user_id=model.initiated_by_user_id,
        amount_minor=model.amount_minor,
        currency=CurrencyEnum(model.currency),
        status=SandboxTopUpStatusEnum(model.status),
        rejection_code=SandboxTopUpRejectionCodeEnum(model.rejection_code) if model.rejection_code is not None else None,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


def _to_model(
        entity: SandboxTopUp
) -> SqlAlchemySandboxTopUpModel:
    return SqlAlchemySandboxTopUpModel(
        id=entity.id,
        wallet_id=entity.wallet_id,
        initiated_by_user_id=entity.initiated_by_user_id,
        amount_minor=entity.amount_minor,
        currency=entity.currency.value,
        status=entity.status.value,
        rejection_code=entity.rejection_code.value if entity.rejection_code is not None else None,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        completed_at=entity.completed_at,
    )


class SqlAlchemySandboxTopUpRepository(
    ISandboxTopUpRepository,
    SqlAlchemyBaseRepository
):
    async def add(self, sandbox_top_up: SandboxTopUp) -> None:
        model = _to_model(sandbox_top_up)
        self.session.add(model)
        await self.session.flush()

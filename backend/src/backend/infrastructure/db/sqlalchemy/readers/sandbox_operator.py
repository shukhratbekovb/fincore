from uuid import UUID
from sqlalchemy import select

from backend.application.sandbox_top_up.interfaces.operator import ISandboxOperatorReader
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemySandboxOperatorModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


class SqlAlchemySandboxOperatorReader(ISandboxOperatorReader, SqlAlchemyBaseRepository):
    async def is_operator(self, user_id: UUID) -> bool:
        stmt = select(SqlAlchemySandboxOperatorModel.user_id).where(SqlAlchemySandboxOperatorModel.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

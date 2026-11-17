from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel


class SqlAlchemySandboxOperatorModel(SqlAlchemyBaseModel):
    __tablename__ = "sandbox_operators"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)

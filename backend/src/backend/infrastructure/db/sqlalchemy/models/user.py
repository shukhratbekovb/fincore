from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin, SqlAlchemyTimeActionMixin


class SqlAlchemyUserModel(
    SqlAlchemyIdentityMixin,
    SqlAlchemyTimeActionMixin,
    SqlAlchemyBaseModel
):
    __tablename__ = 'users'

    username: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(30))
    last_login_at: Mapped[datetime | None]

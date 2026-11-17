from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Mapped, mapped_column


class SqlAlchemyIdentityMixin:
    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)


class SqlAlchemyTimeActionMixin:
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin, SqlAlchemyTimeActionMixin


class SqlAlchemyWalletModel(SqlAlchemyIdentityMixin, SqlAlchemyTimeActionMixin, SqlAlchemyBaseModel):
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("number", name="uq_wallets_number"),
        UniqueConstraint("id", "currency", name="uq_wallets_id_currency"),
        CheckConstraint("status IN ('active', 'frozen', 'closed')", name="ck_wallets_status"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 64", name="ck_wallets_name"),
        CheckConstraint("number ~ '^[0-9]{20}$'", name="ck_wallets_number"),
        CheckConstraint("currency IN ('USD','EUR','JPY','CHF','GBP','UZS','CAD','RUB')", name="ck_wallets_currency"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    number: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20))

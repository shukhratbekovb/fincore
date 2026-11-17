from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyTimeActionMixin


class SqlAlchemyWalletBalanceModel(SqlAlchemyTimeActionMixin, SqlAlchemyBaseModel):
    __tablename__ = "wallet_balances"
    __table_args__ = (
        CheckConstraint("posted_minor >= 0", name="ck_wallet_balances_nonnegative"),
        CheckConstraint("version >= 0", name="ck_wallet_balances_version"),
    )

    wallet_id: Mapped[UUID] = mapped_column(ForeignKey("wallets.id"), primary_key=True)
    posted_minor: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    version: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")

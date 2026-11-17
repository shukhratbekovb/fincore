from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin, SqlAlchemyTimeActionMixin


class SqlAlchemyTransferModel(SqlAlchemyIdentityMixin, SqlAlchemyTimeActionMixin, SqlAlchemyBaseModel):
    __tablename__ = "transfers"
    __table_args__ = (
        ForeignKeyConstraint(["sender_wallet_id", "currency"], ["wallets.id", "wallets.currency"]),
        ForeignKeyConstraint(["receiver_wallet_id", "currency"], ["wallets.id", "wallets.currency"]),
        UniqueConstraint("id", "currency", name="uq_transfers_id_currency"),
        CheckConstraint("sender_wallet_id <> receiver_wallet_id", name="ck_transfers_wallets"),
        CheckConstraint("amount_minor > 0", name="ck_transfers_amount"),
        CheckConstraint("(status = 'completed' AND completed_at IS NOT NULL AND rejection_code IS NULL) OR (status = 'rejected' AND completed_at IS NULL AND rejection_code IS NOT NULL)", name="ck_transfers_state"),
        CheckConstraint("updated_at >= created_at AND (completed_at IS NULL OR completed_at BETWEEN created_at AND updated_at)", name="ck_transfers_time"),
        CheckConstraint("rejection_code IS NULL OR rejection_code IN ('insufficient_funds','wallet_not_active','currency_mismatch','balance_overflow')", name="ck_transfers_rejection"),
    )
    sender_wallet_id: Mapped[UUID] = mapped_column(index=True)
    receiver_wallet_id: Mapped[UUID] = mapped_column(index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20))
    rejection_code: Mapped[str | None] = mapped_column(String(50))
    completed_at: Mapped[datetime | None]

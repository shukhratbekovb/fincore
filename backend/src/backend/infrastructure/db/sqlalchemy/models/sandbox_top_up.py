from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin, SqlAlchemyTimeActionMixin


class SqlAlchemySandboxTopUpModel(SqlAlchemyIdentityMixin, SqlAlchemyTimeActionMixin, SqlAlchemyBaseModel):
    __tablename__ = "sandbox_top_ups"
    __table_args__ = (
        ForeignKeyConstraint(["wallet_id", "currency"], ["wallets.id", "wallets.currency"]),
        UniqueConstraint("id", "currency", name="uq_sandbox_top_ups_id_currency"),
        CheckConstraint("amount_minor > 0", name="ck_top_ups_amount"),
        CheckConstraint("(status = 'completed' AND completed_at IS NOT NULL AND rejection_code IS NULL) OR (status = 'rejected' AND completed_at IS NULL AND rejection_code IS NOT NULL)", name="ck_top_ups_state"),
        CheckConstraint("updated_at >= created_at AND (completed_at IS NULL OR completed_at BETWEEN created_at AND updated_at)", name="ck_top_ups_time"),
        CheckConstraint("rejection_code IS NULL OR rejection_code IN ('wallet_not_active','balance_overflow','limit_exceeded')", name="ck_top_ups_rejection"),
    )
    wallet_id: Mapped[UUID] = mapped_column(index=True)
    initiated_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20))
    rejection_code: Mapped[str | None] = mapped_column(String(50))
    completed_at: Mapped[datetime | None]

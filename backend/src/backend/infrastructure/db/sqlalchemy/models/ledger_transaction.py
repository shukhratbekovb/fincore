from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin


class SqlAlchemyLedgerTransactionModel(SqlAlchemyIdentityMixin, SqlAlchemyBaseModel):
    __tablename__ = "ledger_transactions"
    __table_args__ = (
        UniqueConstraint("transfer_id", name="uq_journals_transfer"),
        UniqueConstraint("sandbox_top_up_id", name="uq_journals_top_up"),
        UniqueConstraint("id", "currency", name="uq_journals_id_currency"),
        ForeignKeyConstraint(["transfer_id", "currency"], ["transfers.id", "transfers.currency"]),
        ForeignKeyConstraint(["sandbox_top_up_id", "currency"], ["sandbox_top_ups.id", "sandbox_top_ups.currency"]),
        CheckConstraint("(kind = 'p2p_transfer' AND transfer_id IS NOT NULL AND sandbox_top_up_id IS NULL) OR (kind = 'sandbox_topup' AND transfer_id IS NULL AND sandbox_top_up_id IS NOT NULL)", name="ck_journals_source"),
        CheckConstraint("reference IS NULL OR length(trim(reference)) > 0", name="ck_journals_reference"),
    )
    transfer_id: Mapped[UUID | None]
    sandbox_top_up_id: Mapped[UUID | None]
    kind: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3))
    posted_at: Mapped[datetime] = mapped_column(index=True)
    reference: Mapped[str | None] = mapped_column(String(128))

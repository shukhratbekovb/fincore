from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin


class SqlAlchemyLedgerEntryModel(SqlAlchemyIdentityMixin, SqlAlchemyBaseModel):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        ForeignKeyConstraint(["ledger_transaction_id", "currency"], ["ledger_transactions.id", "ledger_transactions.currency"]),
        ForeignKeyConstraint(["ledger_account_id", "currency"], ["ledger_accounts.id", "ledger_accounts.currency"]),
        UniqueConstraint("ledger_transaction_id", "ledger_account_id", "side", name="uq_entries_account_side"),
        CheckConstraint("amount_minor > 0", name="ck_entries_amount"),
        CheckConstraint("side IN ('debit','credit')", name="ck_entries_side"),
    )
    ledger_transaction_id: Mapped[UUID] = mapped_column(index=True)
    ledger_account_id: Mapped[UUID] = mapped_column(index=True)
    side: Mapped[str] = mapped_column(String(6))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime]

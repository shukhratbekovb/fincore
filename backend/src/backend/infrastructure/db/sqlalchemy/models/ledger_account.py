from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin


class SqlAlchemyLedgerAccountModel(SqlAlchemyIdentityMixin, SqlAlchemyBaseModel):
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        UniqueConstraint("code", name="uq_ledger_accounts_code"),
        UniqueConstraint("wallet_id", name="uq_ledger_accounts_wallet"),
        UniqueConstraint("id", "currency", name="uq_ledger_accounts_id_currency"),
        ForeignKeyConstraint(["wallet_id", "currency"], ["wallets.id", "wallets.currency"], name="fk_ledger_accounts_wallet_currency"),
        CheckConstraint("status IN ('active', 'closed')", name="ck_ledger_accounts_status"),
        CheckConstraint(
            "(wallet_id IS NOT NULL AND account_type = 'liability' "
            "AND code = 'WALLET:' || CAST(wallet_id AS VARCHAR) || ':' || currency) OR "
            "(wallet_id IS NULL AND account_type = 'asset' AND code = 'SYS:SIM_FUNDING:' || currency)",
            name="ck_ledger_accounts_purpose",
        ),
        CheckConstraint("currency IN ('USD','EUR','JPY','CHF','GBP','UZS','CAD','RUB')", name="ck_ledger_accounts_currency"),
    )

    code: Mapped[str] = mapped_column(String(80))
    account_type: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime]
    wallet_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(String(20))

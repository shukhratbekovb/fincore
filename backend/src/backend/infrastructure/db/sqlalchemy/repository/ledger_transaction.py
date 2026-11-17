from backend.application.ledger_transaction.interfaces.repository import ILedgerTransactionRepository
from backend.domain.ledger_entry.entities import LedgerEntry
from backend.domain.ledger_entry.enums import LedgerEntrySideEnum
from backend.domain.ledger_transaction.entities import LedgerTransaction
from backend.domain.ledger_transaction.enums import LedgerTransactionKindEnum
from backend.domain.share.enums import CurrencyEnum
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyLedgerTransactionModel, SqlAlchemyLedgerEntryModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_entity(
        model: SqlAlchemyLedgerTransactionModel,
        entries: list[SqlAlchemyLedgerEntryModel],
) -> LedgerTransaction:
    return LedgerTransaction(
        id=model.id, transfer_id=model.transfer_id, sandbox_top_up_id=model.sandbox_top_up_id,
        kind=LedgerTransactionKindEnum(model.kind), currency=CurrencyEnum(model.currency),
        posted_at=model.posted_at, reference=model.reference,
        entries=tuple(LedgerEntry(
            id=entry.id, ledger_transaction_id=entry.ledger_transaction_id,
            ledger_account_id=entry.ledger_account_id, side=LedgerEntrySideEnum(entry.side),
            amount_minor=entry.amount_minor, currency=CurrencyEnum(entry.currency), created_at=entry.created_at,
        ) for entry in entries),
    )


def _to_model(
        entity: LedgerTransaction
) -> SqlAlchemyLedgerTransactionModel:
    return SqlAlchemyLedgerTransactionModel(
        id=entity.id, transfer_id=entity.transfer_id, sandbox_top_up_id=entity.sandbox_top_up_id,
        kind=entity.kind.value, currency=entity.currency.value, posted_at=entity.posted_at, reference=entity.reference,
    )


class SqlAlchemyLedgerTransactionRepository(ILedgerTransactionRepository, SqlAlchemyBaseRepository):
    async def add(self, journal: LedgerTransaction) -> None:
        model = _to_model(journal)
        self.session.add(model)
        await self.session.flush()
        for entry in journal.entries:
            self.session.add(SqlAlchemyLedgerEntryModel(
                id=entry.id, ledger_transaction_id=entry.ledger_transaction_id,
                ledger_account_id=entry.ledger_account_id, side=entry.side.value,
                amount_minor=entry.amount_minor, currency=entry.currency.value, created_at=entry.created_at,
            ))
        await self.session.flush()

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from backend.application.reconciliation.dtos import ReconcileLedgerCommand, ReconciliationReport
from backend.application.reconciliation.queries.reconcile_ledger import ReconcileLedgerQuery
from backend.infrastructure.db.sqlalchemy.core.database import create_engine, create_session_factory
from backend.infrastructure.db.sqlalchemy.readers.reconciliation import SqlAlchemyLedgerReconciliationReader
from backend.infrastructure.settings import get_settings


def _json_value(value):
    if isinstance(value, (UUID, datetime)):
        return str(value)
    raise TypeError(f"Unsupported report value: {type(value).__name__}")


def serialize_report(report: ReconciliationReport) -> str:
    return json.dumps({
        **asdict(report), 'is_consistent': report.is_consistent, 'issue_count': report.issue_count,
    }, default=_json_value, ensure_ascii=False, indent=2)


async def reconcile(sample_limit: int) -> ReconciliationReport:
    engine = create_engine(get_settings())
    try:
        reader = SqlAlchemyLedgerReconciliationReader(create_session_factory(engine))
        return await ReconcileLedgerQuery(reader).execute(ReconcileLedgerCommand(sample_limit))
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only ledger/projection reconciliation; never repairs data")
    parser.add_argument('--sample-limit', type=int, default=10, choices=range(1, 101), metavar='1..100')
    args = parser.parse_args()
    try:
        report = asyncio.run(reconcile(args.sample_limit))
    except Exception as exc:
        # Connection exception text can contain infrastructure credentials.
        print(f"Ledger reconciliation failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    print(serialize_report(report))
    return 0 if report.is_consistent else 1


if __name__ == '__main__':
    raise SystemExit(main())

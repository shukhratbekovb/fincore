import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.application.reconciliation.dtos import (
    ReconcileLedgerCommand, ReconciliationExample, ReconciliationFinding, ReconciliationReport,
)
from backend.application.reconciliation.queries.reconcile_ledger import ReconcileLedgerQuery
from backend.bootstrap.reconcile_ledger import serialize_report


async def test_snapshot_report_and_sampling_are_forwarded_without_mutation(now):
    report = ReconciliationReport(now, 4, 7, 14, ())
    reader = AsyncMock()
    reader.reconcile.return_value = report
    result = await ReconcileLedgerQuery(reader).execute(ReconcileLedgerCommand(3))
    assert result is report and result.is_consistent and result.issue_count == 0
    reader.reconcile.assert_awaited_once_with(sample_limit=3)


@pytest.mark.parametrize('limit', [True, False, 0, -1, 101, 1.5, '10', None])
async def test_invalid_limit_cannot_start_full_database_scan(limit):
    reader = AsyncMock()
    with pytest.raises(ValueError):
        await ReconcileLedgerQuery(reader).execute(ReconcileLedgerCommand(limit))
    reader.reconcile.assert_not_awaited()


def test_json_preserves_arbitrary_precision_counts_and_money(now):
    example = ReconciliationExample('wallet', uuid4(), 'USD', 2 ** 80, 2 ** 63 - 1)
    report = ReconciliationReport(now, 1000, 1000, 2000, (
        ReconciliationFinding('wallet_balance_mismatch', 147, (example,)),
    ))
    result = json.loads(serialize_report(report))
    assert result['is_consistent'] is False and result['issue_count'] == 147
    assert result['findings'][0]['examples'][0]['expected_minor'] == 2 ** 80
    assert result['findings'][0]['examples'][0]['actual_minor'] == 2 ** 63 - 1
    assert len(result['findings'][0]['examples']) == 1


@pytest.mark.parametrize('consistent,exit_code', [(True, 0), (False, 1)])
def test_cli_exit_status_matches_report(monkeypatch, capsys, now, consistent, exit_code):
    from backend.bootstrap import reconcile_ledger as cli
    report = ReconciliationReport(now, 1, 0, 0, () if consistent else (
        ReconciliationFinding('wallet_balance_missing', 1, ()),
    ))
    call = AsyncMock(return_value=report)
    monkeypatch.setattr(cli, 'reconcile', call)
    monkeypatch.setattr('sys.argv', ['reconcile', '--sample-limit', '2'])
    assert cli.main() == exit_code
    output = capsys.readouterr()
    assert json.loads(output.out)['is_consistent'] is consistent
    assert output.err == ''
    call.assert_awaited_once_with(2)


def test_cli_failure_never_leaks_connection_credentials(monkeypatch, capsys):
    from backend.bootstrap import reconcile_ledger as cli
    monkeypatch.setattr(cli, 'reconcile', AsyncMock(side_effect=RuntimeError('postgres://user:secret@host')))
    monkeypatch.setattr('sys.argv', ['reconcile'])
    assert cli.main() == 2
    output = capsys.readouterr()
    assert output.out == '' and output.err == 'Ledger reconciliation failed (RuntimeError)\n'


async def test_cli_disposes_engine_after_database_failure(monkeypatch):
    from backend.bootstrap import reconcile_ledger as cli
    engine = AsyncMock()
    monkeypatch.setattr(cli, 'get_settings', lambda: object())
    monkeypatch.setattr(cli, 'create_engine', lambda settings: engine)
    monkeypatch.setattr(cli, 'create_session_factory', lambda current: object())
    reader = AsyncMock()
    reader.reconcile.side_effect = RuntimeError('query failed')
    monkeypatch.setattr(cli, 'SqlAlchemyLedgerReconciliationReader', lambda factory: reader)
    with pytest.raises(RuntimeError, match='query failed'):
        await cli.reconcile(10)
    engine.dispose.assert_awaited_once()

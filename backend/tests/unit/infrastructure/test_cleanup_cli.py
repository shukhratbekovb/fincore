import asyncio
import json
import signal
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.bootstrap import cleanup as cleanup_cli
from backend.application.maintenance.dtos import CleanupReport
from backend.infrastructure.maintenance.settings import CleanupSettings


@pytest.fixture
def report():
    return CleanupReport(
        as_of=datetime(2026, 11, 15, tzinfo=timezone.utc), dry_run=True,
        sessions=2, refresh_tokens=5, verification_challenges=3,
        outbox_messages=1, idempotency_records=4,
    )


def test_main_dry_run_prints_json_report_and_forwards_bounded_options(monkeypatch, capsys, report):
    run = AsyncMock(return_value=report)
    monkeypatch.setattr(cleanup_cli, 'cleanup', run)
    monkeypatch.setattr('sys.argv', ['cleanup', '--dry-run', '--batch-size', '1000', '--max-batches', '1'])
    assert cleanup_cli.main() == 0
    run.assert_awaited_once_with(dry_run=True, batch_size=1000, max_batches=1)
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output['dry_run'] is True
    assert output['as_of'] == '2026-11-15 00:00:00+00:00'
    assert output['sessions'] == 2 and output['refresh_tokens'] == 5
    assert output['idempotency_records'] == 4
    assert captured.err == ''


def test_main_failure_returns_nonzero_and_does_not_print_connection_credentials(monkeypatch, capsys):
    run = AsyncMock(side_effect=RuntimeError('postgresql://admin:secret-password@private-host/fincore'))
    monkeypatch.setattr(cleanup_cli, 'cleanup', run)
    monkeypatch.setattr('sys.argv', ['cleanup'])
    assert cleanup_cli.main() == 2
    run.assert_awaited_once_with(dry_run=False, batch_size=None, max_batches=None)
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err.strip() == 'Cleanup failed (RuntimeError)'
    assert 'secret-password' not in captured.err
    assert 'private-host' not in captured.err


def test_main_loop_uses_scheduler_without_printing_duplicate_report(monkeypatch, capsys):
    run = AsyncMock()
    monkeypatch.setattr(cleanup_cli, 'run_loop', run)
    monkeypatch.setattr('sys.argv', ['cleanup', '--loop', '--batch-size', '5'])
    assert cleanup_cli.main() == 0
    run.assert_awaited_once_with(batch_size=5, max_batches=None)
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('arguments', [
    ['--batch-size', '0'], ['--batch-size', '1001'], ['--batch-size', 'invalid'],
    ['--max-batches', '0'], ['--max-batches', '1001'], ['--max-batches', '-1'],
    ['--loop', '--dry-run'],
])
def test_main_rejects_unbounded_or_conflicting_options_before_starting_cleanup(monkeypatch, capsys, arguments):
    run, scheduler = AsyncMock(), AsyncMock()
    monkeypatch.setattr(cleanup_cli, 'cleanup', run)
    monkeypatch.setattr(cleanup_cli, 'run_loop', scheduler)
    monkeypatch.setattr('sys.argv', ['cleanup', *arguments])
    with pytest.raises(SystemExit) as exc:
        cleanup_cli.main()
    assert exc.value.code == 2
    run.assert_not_called()
    scheduler.assert_not_called()
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('overrides', [False, True])
async def test_cleanup_builds_configured_policy_and_always_disposes_engine(monkeypatch, report, overrides):
    settings = CleanupSettings(_env_file=None, cleanup_batch_size=40, cleanup_max_batches=3,
                               cleanup_challenge_retention_days=9)
    engine = SimpleNamespace(dispose=AsyncMock())
    execute = AsyncMock(return_value=report)
    factory, store = object(), object()
    monkeypatch.setattr(cleanup_cli, 'CleanupSettings', lambda: settings)
    monkeypatch.setattr(cleanup_cli, 'get_settings', Mock())
    monkeypatch.setattr(cleanup_cli, 'create_engine', Mock(return_value=engine))
    monkeypatch.setattr(cleanup_cli, 'create_session_factory', Mock(return_value=factory))
    build_store = Mock(return_value=store)
    build_case = Mock(return_value=SimpleNamespace(execute=execute))
    monkeypatch.setattr(cleanup_cli, 'SqlAlchemyMaintenanceStore', build_store)
    monkeypatch.setattr(cleanup_cli, 'CleanupExpiredDataUseCase', build_case)
    result = await cleanup_cli.cleanup(dry_run=True, **({'batch_size': 10, 'max_batches': 2} if overrides else {}))
    assert result is report
    command = execute.call_args.args[0]
    assert command.dry_run is True
    assert command.batch_size == (10 if overrides else 40)
    assert command.max_batches == (2 if overrides else 3)
    assert command.policy == settings.policy()
    build_store.assert_called_once_with(factory)
    build_case.assert_called_once_with(store)
    engine.dispose.assert_awaited_once()


@pytest.mark.parametrize('stage', ['factory', 'execute'])
async def test_cleanup_disposes_engine_when_initialization_or_execution_fails(monkeypatch, stage):
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(cleanup_cli, 'CleanupSettings', lambda: CleanupSettings(_env_file=None))
    monkeypatch.setattr(cleanup_cli, 'get_settings', Mock())
    monkeypatch.setattr(cleanup_cli, 'create_engine', Mock(return_value=engine))
    build_factory = Mock(side_effect=RuntimeError('connection details')) if stage == 'factory' else Mock()
    monkeypatch.setattr(cleanup_cli, 'create_session_factory', build_factory)
    monkeypatch.setattr(cleanup_cli, 'SqlAlchemyMaintenanceStore', Mock())
    execute = AsyncMock(side_effect=RuntimeError('connection details'))
    monkeypatch.setattr(cleanup_cli, 'CleanupExpiredDataUseCase', Mock(return_value=SimpleNamespace(execute=execute)))
    with pytest.raises(RuntimeError):
        await cleanup_cli.cleanup(dry_run=False)
    engine.dispose.assert_awaited_once()
    if stage == 'factory':
        execute.assert_not_awaited()


async def test_loop_retries_failure_then_stops_on_sigterm_without_delay(monkeypatch, capsys, report):
    loop = asyncio.get_running_loop()
    handlers = {}
    add = Mock(side_effect=lambda sig, callback: handlers.__setitem__(sig, callback))
    remove = Mock()
    monkeypatch.setattr(loop, 'add_signal_handler', add)
    monkeypatch.setattr(loop, 'remove_signal_handler', remove)
    monkeypatch.setattr(cleanup_cli, 'CleanupSettings', lambda: SimpleNamespace(cleanup_interval_seconds=3600))
    attempts = 0
    async def run(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError('postgresql://admin:secret-password@private-host/fincore')
        handlers[signal.SIGTERM]()
        return report
    run = AsyncMock(side_effect=run)
    monkeypatch.setattr(cleanup_cli, 'cleanup', run)
    waits = []
    async def wait(awaitable, *, timeout):
        waits.append(timeout)
        if len(waits) == 1:
            awaitable.close()
            raise TimeoutError()
        return await awaitable
    monkeypatch.setattr(cleanup_cli.asyncio, 'wait_for', wait)
    await cleanup_cli.run_loop(batch_size=10, max_batches=2)
    assert run.await_count == 2
    assert all(call.kwargs == {'dry_run': False, 'batch_size': 10, 'max_batches': 2} for call in run.call_args_list)
    assert waits == [3600, 3600]
    assert set(handlers) == {signal.SIGINT, signal.SIGTERM}
    assert [call.args[0] for call in remove.call_args_list] == [signal.SIGINT, signal.SIGTERM]
    captured = capsys.readouterr()
    assert captured.err.strip() == 'Cleanup failed (RuntimeError)'
    assert 'secret-password' not in captured.err and 'private-host' not in captured.err
    assert json.loads(captured.out)['sessions'] == report.sessions


async def test_loop_cancellation_removes_signal_handlers(monkeypatch):
    loop = asyncio.get_running_loop()
    add, remove = Mock(), Mock()
    monkeypatch.setattr(loop, 'add_signal_handler', add)
    monkeypatch.setattr(loop, 'remove_signal_handler', remove)
    monkeypatch.setattr(cleanup_cli, 'CleanupSettings', lambda: CleanupSettings(_env_file=None))
    monkeypatch.setattr(cleanup_cli, 'cleanup', AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await cleanup_cli.run_loop()
    assert add.call_count == remove.call_count == 2

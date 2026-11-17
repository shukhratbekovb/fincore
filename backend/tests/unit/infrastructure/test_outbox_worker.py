import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.bootstrap import outbox_worker
from backend.infrastructure.notifications.settings import OutboxWorkerSettings, SmtpSettings


def test_bootstrap_builds_dependencies_from_explicit_settings():
    processor = outbox_worker.build_processor(Mock(), SmtpSettings(_env_file=None), OutboxWorkerSettings(_env_file=None, outbox_concurrency=2))
    assert processor.concurrency == 2
    assert processor.handlers


@pytest.mark.parametrize('failure', [False, True])
async def test_loop_waits_when_idle_or_database_unavailable(failure, caplog):
    stop = asyncio.Event()
    processor = AsyncMock()
    async def poll():
        stop.set()
        if failure:
            raise RuntimeError('secret connection details')
        return 0
    processor.run_once.side_effect = poll
    await outbox_worker.run_loop(processor, stop, 0.001)
    processor.run_once.assert_awaited_once()
    assert 'secret connection details' not in caplog.text


async def test_loop_polls_again_after_idle_timeout():
    stop = asyncio.Event()
    processor = AsyncMock()
    calls = 0
    async def poll():
        nonlocal calls
        calls += 1
        if calls == 2:
            stop.set()
        return 0
    processor.run_once.side_effect = poll
    await outbox_worker.run_loop(processor, stop, 0.001)
    assert calls == 2


@pytest.mark.parametrize('once', [True, False])
async def test_worker_disposes_engine_and_cleans_signal_handlers(monkeypatch, once):
    engine = SimpleNamespace(dispose=AsyncMock())
    processor = AsyncMock()
    monkeypatch.setattr(outbox_worker, 'SmtpSettings', lambda: SmtpSettings(_env_file=None))
    monkeypatch.setattr(outbox_worker, 'OutboxWorkerSettings', lambda: OutboxWorkerSettings(_env_file=None))
    monkeypatch.setattr(outbox_worker, 'get_settings', Mock())
    monkeypatch.setattr(outbox_worker, 'create_engine', Mock(return_value=engine))
    monkeypatch.setattr(outbox_worker, 'create_session_factory', Mock())
    monkeypatch.setattr(outbox_worker, 'build_processor', Mock(return_value=processor))
    loop = asyncio.get_running_loop()
    add, remove = Mock(), Mock()
    monkeypatch.setattr(loop, 'add_signal_handler', add)
    monkeypatch.setattr(loop, 'remove_signal_handler', remove)
    monkeypatch.setattr(outbox_worker, 'run_loop', AsyncMock())
    await outbox_worker.run(once=once)
    engine.dispose.assert_awaited_once()
    if once:
        processor.run_once.assert_awaited_once()
        add.assert_not_called()
    else:
        assert add.call_count == remove.call_count == 2


async def test_worker_disposes_engine_if_batch_fails(monkeypatch):
    engine = SimpleNamespace(dispose=AsyncMock())
    processor = AsyncMock()
    processor.run_once.side_effect = RuntimeError('failure')
    monkeypatch.setattr(outbox_worker, 'SmtpSettings', lambda: SmtpSettings(_env_file=None))
    monkeypatch.setattr(outbox_worker, 'OutboxWorkerSettings', lambda: OutboxWorkerSettings(_env_file=None))
    monkeypatch.setattr(outbox_worker, 'get_settings', Mock())
    monkeypatch.setattr(outbox_worker, 'create_engine', Mock(return_value=engine))
    monkeypatch.setattr(outbox_worker, 'create_session_factory', Mock())
    monkeypatch.setattr(outbox_worker, 'build_processor', Mock(return_value=processor))
    with pytest.raises(RuntimeError):
        await outbox_worker.run(once=True)
    engine.dispose.assert_awaited_once()

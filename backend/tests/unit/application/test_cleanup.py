from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.application.maintenance.dtos import CleanupExpiredDataCommand, CleanupPolicy, CleanupReport
from backend.application.maintenance.use_cases.cleanup import CleanupExpiredDataUseCase
from backend.infrastructure.maintenance.settings import CleanupSettings
from backend.infrastructure.security.idempotency import idempotency_key_digest
from uuid import uuid4


async def test_cleanup_passes_validated_policy_and_returns_report():
    cmd = CleanupExpiredDataCommand(dry_run=True, batch_size=1, max_batches=2)
    report = CleanupReport(as_of=datetime.now(timezone.utc), dry_run=True, sessions=3)
    store = AsyncMock(cleanup=AsyncMock(return_value=report))
    assert await CleanupExpiredDataUseCase(store).execute(cmd) is report
    store.cleanup.assert_awaited_once_with(cmd)


@pytest.mark.parametrize('values', [
    {'batch_size': 0}, {'batch_size': 1001}, {'batch_size': True},
    {'max_batches': 0}, {'max_batches': 1001}, {'max_batches': False}, {'dry_run': 1},
    {'policy': None}, {'policy': CleanupPolicy(session_retention=timedelta(0))},
    {'policy': CleanupPolicy(idempotency_retention=timedelta(hours=23))},
    {'policy': CleanupPolicy(outbox_retention=timedelta(days=36501))},
    {'policy': CleanupPolicy(challenge_retention='7 days')},
])
async def test_cleanup_rejects_unsafe_parameters_before_store(values):
    store = AsyncMock()
    with pytest.raises((TypeError, ValueError)):
        await CleanupExpiredDataUseCase(store).execute(replace(CleanupExpiredDataCommand(), **values))
    store.cleanup.assert_not_called()


def test_cleanup_settings_have_positive_retention_and_bounded_batches():
    settings = CleanupSettings(_env_file=None, cleanup_session_retention_days=14)
    assert settings.policy().session_retention == timedelta(days=14)
    assert settings.policy().idempotency_retention == timedelta(days=7)
    for values in ({'cleanup_batch_size': 0}, {'cleanup_max_batches': 1001}, {'cleanup_idempotency_retention_days': 0}):
        with pytest.raises(ValidationError):
            CleanupSettings(_env_file=None, **values)


def test_receipt_identity_is_actor_scope_and_key_specific():
    actor = uuid4()
    first = idempotency_key_digest(user_id=actor, scope='transfer.create', key='same')
    assert len(first) == 64
    assert first == idempotency_key_digest(user_id=actor, scope='transfer.create', key='same')
    assert first != idempotency_key_digest(user_id=uuid4(), scope='transfer.create', key='same')
    assert first != idempotency_key_digest(user_id=actor, scope='sandbox_top_up.create', key='same')
    assert first != idempotency_key_digest(user_id=actor, scope='transfer.create', key='different')

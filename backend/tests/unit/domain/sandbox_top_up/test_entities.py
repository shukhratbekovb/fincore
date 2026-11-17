from dataclasses import replace
from datetime import timedelta, timezone
from uuid import uuid4

import pytest

from backend.domain.sandbox_top_up.entities import MAX_SANDBOX_TOP_UP_AMOUNT_MINOR, SandboxTopUp
from backend.domain.sandbox_top_up.enums import SandboxTopUpRejectionCodeEnum, SandboxTopUpStatusEnum
from backend.domain.sandbox_top_up.errors import (
    InvalidSandboxTopUpAmountError, InvalidSandboxTopUpStateError, SandboxTopUpNotPendingError,
)
from backend.domain.share.entities import BaseEntity
from backend.domain.share.enums import CurrencyEnum
from backend.domain.share.mixins import IdentityMixin, TimeActionMixin


@pytest.fixture
def top_up(now):
    return SandboxTopUp.create(
        wallet_id=uuid4(), initiated_by_user_id=uuid4(), amount_minor=100,
        currency=CurrencyEnum.USD, now=now,
    )


def test_factory_creates_pending_operation_with_explicit_initiator(top_up, now):
    assert isinstance(top_up, BaseEntity)
    assert isinstance(top_up, IdentityMixin)
    assert isinstance(top_up, TimeActionMixin)
    assert top_up.status is SandboxTopUpStatusEnum.PENDING
    assert top_up.created_at == top_up.updated_at == now
    assert top_up.completed_at is None
    assert top_up.rejection_code is None
    assert replace(top_up) == top_up


@pytest.mark.parametrize('amount', [1, MAX_SANDBOX_TOP_UP_AMOUNT_MINOR])
@pytest.mark.parametrize('currency', list(CurrencyEnum))
def test_valid_amount_boundaries_and_currencies(top_up, amount, currency):
    restored = replace(top_up, amount_minor=amount, currency=currency)
    assert restored.amount_minor == amount
    assert restored.currency is currency


@pytest.mark.parametrize('amount', [0, -1, True, False, 1.5, '100', None, MAX_SANDBOX_TOP_UP_AMOUNT_MINOR + 1])
def test_invalid_amount_is_rejected(top_up, amount):
    with pytest.raises(InvalidSandboxTopUpAmountError):
        replace(top_up, amount_minor=amount)


@pytest.mark.parametrize(('field', 'value'), [
    ('id', None), ('wallet_id', 'uuid'), ('initiated_by_user_id', 1),
    ('currency', 'USD'), ('status', 'pending'),
])
def test_invalid_identity_and_enum_types_are_rejected(top_up, field, value):
    with pytest.raises(TypeError):
        replace(top_up, **{field: value})


@pytest.mark.parametrize('field', ['created_at', 'updated_at'])
@pytest.mark.parametrize('invalid_type', [False, True])
def test_invalid_restored_time_is_rejected(top_up, now, field, invalid_type):
    with pytest.raises(InvalidSandboxTopUpStateError):
        replace(top_up, **{field: None if invalid_type else now.replace(tzinfo=None)})


def test_update_cannot_precede_creation(top_up, now):
    with pytest.raises(InvalidSandboxTopUpStateError):
        replace(top_up, updated_at=now - timedelta(seconds=1))


def test_complete_updates_only_status_and_timestamps(top_up, now):
    before = vars(top_up).copy()
    later = (now + timedelta(minutes=1)).astimezone(timezone(timedelta(hours=5)))
    top_up.complete(now=later)
    assert vars(top_up) == {
        **before, 'status': SandboxTopUpStatusEnum.COMPLETED,
        'completed_at': later, 'updated_at': later,
    }
    assert replace(top_up) == top_up


@pytest.mark.parametrize('code', list(SandboxTopUpRejectionCodeEnum))
def test_reject_records_business_reason(top_up, now, code):
    before = vars(top_up).copy()
    later = now + timedelta(minutes=1)
    top_up.reject(code, now=later)
    assert vars(top_up) == {
        **before, 'status': SandboxTopUpStatusEnum.REJECTED,
        'rejection_code': code, 'updated_at': later,
    }
    assert replace(top_up) == top_up


@pytest.mark.parametrize('method', ['complete', 'reject'])
@pytest.mark.parametrize('time_kind', ['naive', 'invalid_type', 'past'])
def test_invalid_transition_time_preserves_state(top_up, now, method, time_kind):
    value = {
        'naive': now.replace(tzinfo=None), 'invalid_type': None,
        'past': now - timedelta(seconds=1),
    }[time_kind]
    before = vars(top_up).copy()
    with pytest.raises(InvalidSandboxTopUpStateError):
        if method == 'complete':
            top_up.complete(now=value)
        else:
            top_up.reject(SandboxTopUpRejectionCodeEnum.WALLET_NOT_ACTIVE, now=value)
    assert vars(top_up) == before


@pytest.mark.parametrize('code', [None, '', ' ', 'wallet_not_active', 'database_error', 1])
def test_invalid_rejection_code_preserves_state(top_up, now, code):
    before = vars(top_up).copy()
    with pytest.raises(InvalidSandboxTopUpStateError):
        top_up.reject(code, now=now)
    assert vars(top_up) == before
    with pytest.raises(InvalidSandboxTopUpStateError):
        replace(top_up, status=SandboxTopUpStatusEnum.REJECTED, rejection_code=code)


@pytest.mark.parametrize('final_status', [SandboxTopUpStatusEnum.COMPLETED, SandboxTopUpStatusEnum.REJECTED])
@pytest.mark.parametrize('method', ['complete', 'reject'])
def test_terminal_state_cannot_transition(top_up, now, final_status, method):
    if final_status == SandboxTopUpStatusEnum.COMPLETED:
        top_up.complete(now=now)
    else:
        top_up.reject(SandboxTopUpRejectionCodeEnum.WALLET_NOT_ACTIVE, now=now)
    before = vars(top_up).copy()
    with pytest.raises(SandboxTopUpNotPendingError):
        if method == 'complete':
            top_up.complete(now=now)
        else:
            top_up.reject(SandboxTopUpRejectionCodeEnum.BALANCE_OVERFLOW, now=now)
    assert vars(top_up) == before


@pytest.mark.parametrize('status', [SandboxTopUpStatusEnum.PENDING, SandboxTopUpStatusEnum.REJECTED])
def test_only_completed_operation_may_have_completion_time(top_up, now, status):
    with pytest.raises(InvalidSandboxTopUpStateError):
        replace(top_up, status=status, completed_at=now)


def test_pending_cannot_have_rejection_code(top_up):
    with pytest.raises(InvalidSandboxTopUpStateError):
        replace(top_up, rejection_code=SandboxTopUpRejectionCodeEnum.WALLET_NOT_ACTIVE)


@pytest.mark.parametrize('time_kind', ['missing', 'naive', 'past', 'future'])
def test_completed_requires_valid_completion_time(top_up, now, time_kind):
    value = {
        'missing': None, 'naive': now.replace(tzinfo=None),
        'past': now - timedelta(seconds=1), 'future': now + timedelta(seconds=1),
    }[time_kind]
    with pytest.raises(InvalidSandboxTopUpStateError):
        replace(top_up, status=SandboxTopUpStatusEnum.COMPLETED, completed_at=value)


def test_completed_cannot_have_rejection_code(top_up, now):
    with pytest.raises(InvalidSandboxTopUpStateError):
        replace(
            top_up, status=SandboxTopUpStatusEnum.COMPLETED, completed_at=now,
            rejection_code=SandboxTopUpRejectionCodeEnum.LIMIT_EXCEEDED,
        )

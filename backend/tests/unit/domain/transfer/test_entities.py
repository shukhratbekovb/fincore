from dataclasses import replace
from datetime import timedelta, timezone
from uuid import uuid4

import pytest

from backend.domain.share.entities import BaseEntity
from backend.domain.share.enums import CurrencyEnum
from backend.domain.share.mixins import IdentityMixin, TimeActionMixin
from backend.domain.transfer.entities import MAX_TRANSFER_AMOUNT_MINOR, Transfer
from backend.domain.transfer.enums import TransferRejectionCodeEnum, TransferStatusEnum
from backend.domain.transfer.errors import (
    InvalidTransferAmountError,
    InvalidTransferStateError,
    SameWalletTransferError,
    TransferNotPendingError,
)


@pytest.fixture
def transfer(now):
    return Transfer.create(
        sender_wallet_id=uuid4(),
        receiver_wallet_id=uuid4(),
        amount_minor=100,
        currency=CurrencyEnum.USD,
        now=now,
    )


def test_factory_creates_pending_transfer_with_shared_timestamp(transfer, now):
    assert isinstance(transfer, BaseEntity)
    assert isinstance(transfer, IdentityMixin)
    assert isinstance(transfer, TimeActionMixin)
    assert transfer.status == TransferStatusEnum.PENDING
    assert transfer.rejection_code is None
    assert transfer.completed_at is None
    assert transfer.created_at == transfer.updated_at == now
    assert replace(transfer).id == transfer.id


@pytest.mark.parametrize('amount', [1, MAX_TRANSFER_AMOUNT_MINOR])
@pytest.mark.parametrize('currency', list(CurrencyEnum))
def test_valid_amount_boundaries_and_currencies(transfer, amount, currency):
    restored = replace(transfer, amount_minor=amount, currency=currency)
    assert restored.amount_minor == amount
    assert restored.currency is currency


@pytest.mark.parametrize('amount', [0, -1, True, False, 1.5, '100', None, MAX_TRANSFER_AMOUNT_MINOR + 1])
def test_invalid_amount_is_rejected(transfer, amount):
    with pytest.raises(InvalidTransferAmountError):
        replace(transfer, amount_minor=amount)


def test_same_wallet_is_rejected(transfer):
    with pytest.raises(SameWalletTransferError):
        replace(transfer, receiver_wallet_id=transfer.sender_wallet_id)


@pytest.mark.parametrize(('field', 'value'), [
    ('id', 'uuid'), ('sender_wallet_id', None), ('receiver_wallet_id', 1),
    ('currency', 'USD'), ('status', 'pending'),
])
def test_invalid_identity_and_enum_types_are_rejected(transfer, field, value):
    with pytest.raises(TypeError):
        replace(transfer, **{field: value})


@pytest.mark.parametrize('field', ['created_at', 'updated_at'])
@pytest.mark.parametrize('invalid_type', [False, True])
def test_invalid_restored_timestamps_are_rejected(transfer, now, field, invalid_type):
    value = None if invalid_type else now.replace(tzinfo=None)
    with pytest.raises(InvalidTransferStateError):
        replace(transfer, **{field: value})


def test_updated_time_cannot_precede_creation(transfer, now):
    with pytest.raises(InvalidTransferStateError):
        replace(transfer, updated_at=now - timedelta(seconds=1))


@pytest.mark.parametrize('method', ['complete', 'reject'])
@pytest.mark.parametrize('time_kind', ['naive', 'invalid_type', 'past'])
def test_invalid_transition_time_preserves_state(transfer, now, method, time_kind):
    value = {
        'naive': now.replace(tzinfo=None),
        'invalid_type': None,
        'past': now - timedelta(seconds=1),
    }[time_kind]
    before = vars(transfer).copy()
    with pytest.raises(InvalidTransferStateError):
        if method == 'complete':
            transfer.complete(now=value)
        else:
            transfer.reject(TransferRejectionCodeEnum.INSUFFICIENT_FUNDS, now=value)
    assert vars(transfer) == before


@pytest.mark.parametrize('offset', [0, 5])
def test_completion_sets_exact_time_and_preserves_business_fields(transfer, now, offset):
    before = vars(transfer).copy()
    later = (now + timedelta(minutes=1)).astimezone(timezone(timedelta(hours=offset)))
    transfer.complete(now=later)
    assert vars(transfer) == {
        **before,
        'status': TransferStatusEnum.COMPLETED,
        'completed_at': later,
        'updated_at': later,
    }
    assert vars(replace(transfer)) == vars(transfer)


@pytest.mark.parametrize('code', list(TransferRejectionCodeEnum))
def test_rejection_sets_code_and_update_time(transfer, now, code):
    before = vars(transfer).copy()
    later = now + timedelta(minutes=1)
    transfer.reject(code, now=later)
    assert vars(transfer) == {
        **before,
        'status': TransferStatusEnum.REJECTED,
        'rejection_code': code,
        'updated_at': later,
    }
    assert vars(replace(transfer)) == vars(transfer)


@pytest.mark.parametrize('code', [None, '', ' ', 'insufficient_funds', 'database_error', 1])
def test_invalid_rejection_code_preserves_state(transfer, now, code):
    before = vars(transfer).copy()
    with pytest.raises(InvalidTransferStateError):
        transfer.reject(code, now=now)
    assert vars(transfer) == before
    with pytest.raises(InvalidTransferStateError):
        replace(transfer, status=TransferStatusEnum.REJECTED, rejection_code=code)


@pytest.mark.parametrize('final_status', [TransferStatusEnum.COMPLETED, TransferStatusEnum.REJECTED])
@pytest.mark.parametrize('method', ['complete', 'reject'])
def test_terminal_state_cannot_transition_again(transfer, now, final_status, method):
    if final_status == TransferStatusEnum.COMPLETED:
        transfer.complete(now=now)
    else:
        transfer.reject(TransferRejectionCodeEnum.INSUFFICIENT_FUNDS, now=now)
    before = vars(transfer).copy()
    with pytest.raises(TransferNotPendingError):
        if method == 'complete':
            transfer.complete(now=now)
        else:
            transfer.reject(TransferRejectionCodeEnum.WALLET_NOT_ACTIVE, now=now)
    assert vars(transfer) == before


@pytest.mark.parametrize('status', [TransferStatusEnum.PENDING, TransferStatusEnum.REJECTED])
def test_only_completed_transfer_may_have_completion_time(transfer, now, status):
    with pytest.raises(InvalidTransferStateError):
        replace(transfer, status=status, completed_at=now)


def test_pending_transfer_cannot_have_rejection_code(transfer):
    with pytest.raises(InvalidTransferStateError):
        replace(transfer, rejection_code=TransferRejectionCodeEnum.WALLET_NOT_ACTIVE)


@pytest.mark.parametrize('time_kind', ['missing', 'naive', 'before_creation', 'after_update'])
def test_completed_transfer_requires_consistent_completion_time(transfer, now, time_kind):
    completed_at = {
        'missing': None,
        'naive': now.replace(tzinfo=None),
        'before_creation': now - timedelta(seconds=1),
        'after_update': now + timedelta(seconds=1),
    }[time_kind]
    with pytest.raises(InvalidTransferStateError):
        replace(transfer, status=TransferStatusEnum.COMPLETED, completed_at=completed_at)


def test_completed_transfer_cannot_have_rejection_code(transfer, now):
    with pytest.raises(InvalidTransferStateError):
        replace(
            transfer,
            status=TransferStatusEnum.COMPLETED,
            completed_at=now,
            rejection_code=TransferRejectionCodeEnum.CURRENCY_MISMATCH,
        )


def test_factory_generates_distinct_ids(transfer, now):
    other = Transfer.create(
        sender_wallet_id=transfer.sender_wallet_id,
        receiver_wallet_id=transfer.receiver_wallet_id,
        amount_minor=100,
        currency=CurrencyEnum.USD,
        now=now,
    )
    assert transfer.id != other.id

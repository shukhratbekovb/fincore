from datetime import timedelta
from uuid import uuid4

import pytest

from backend.domain.share.entities import BaseEntity
from backend.domain.share.mixins import TimeActionMixin
from backend.domain.wallet_balance.entities import MAX_BALANCE_MINOR, WalletBalance
from backend.domain.wallet_balance.errors import (
    InsufficientFundsError, InvalidBalanceAmountError, InvalidWalletBalanceError,
    WalletBalanceOverflowError,
)


@pytest.fixture
def balance(now):
    return WalletBalance.create(wallet_id=uuid4(), now=now)


def test_new_balance_is_zero_and_identified_by_wallet(balance, now):
    assert isinstance(balance, BaseEntity)
    assert isinstance(balance, TimeActionMixin)
    assert balance.posted_minor == balance.available_minor == balance.version == 0
    assert balance.created_at == balance.updated_at == now
    assert not hasattr(balance, 'id')


def test_credit_and_debit_update_projection_and_version(balance, now):
    balance.credit(50000, now=now)
    later = now + timedelta(minutes=1)
    balance.debit(10000, now=later)
    assert balance.posted_minor == balance.available_minor == 40000
    assert balance.version == 2
    assert balance.updated_at == later
    assert balance.created_at == now


def test_spending_full_balance_is_allowed(balance, now):
    balance.credit(1, now=now)
    balance.debit(1, now=now)
    assert balance.posted_minor == 0


def test_insufficient_funds_preserves_all_state(balance, now):
    before = vars(balance).copy()
    with pytest.raises(InsufficientFundsError):
        balance.debit(1, now=now)
    assert vars(balance) == before


@pytest.mark.parametrize('method', ['credit', 'debit'])
@pytest.mark.parametrize('amount', [0, -1, True, 1.0, '100', None, MAX_BALANCE_MINOR + 1])
def test_invalid_amount_never_mutates(balance, now, method, amount):
    before = vars(balance).copy()
    with pytest.raises(InvalidBalanceAmountError):
        getattr(balance, method)(amount, now=now)
    assert vars(balance) == before


def test_maximum_balance_boundary(balance, now):
    balance.credit(MAX_BALANCE_MINOR, now=now)
    assert balance.posted_minor == MAX_BALANCE_MINOR
    before = vars(balance).copy()
    with pytest.raises(WalletBalanceOverflowError):
        balance.credit(1, now=now)
    assert vars(balance) == before


@pytest.mark.parametrize('method', ['credit', 'debit'])
def test_version_overflow_never_mutates(balance, now, method):
    restored = WalletBalance(wallet_id=balance.wallet_id, posted_minor=100,
                             version=MAX_BALANCE_MINOR, created_at=now, updated_at=now)
    before = vars(restored).copy()
    with pytest.raises(WalletBalanceOverflowError):
        getattr(restored, method)(1, now=now)
    assert vars(restored) == before


@pytest.mark.parametrize('field', ['posted_minor', 'version'])
@pytest.mark.parametrize('value', [-1, MAX_BALANCE_MINOR + 1, True, 1.0, '0'])
def test_restoration_rejects_invalid_amount_or_version(balance, field, value):
    with pytest.raises(InvalidWalletBalanceError):
        WalletBalance(**{**vars(balance), field: value})


def test_restoration_preserves_balance_version_and_timestamp(balance, now):
    restored = WalletBalance(wallet_id=balance.wallet_id, posted_minor=123, version=7,
                             created_at=now, updated_at=now + timedelta(hours=1))
    assert restored.available_minor == 123
    assert restored.version == 7


@pytest.mark.parametrize('wallet_id', [None, 'uuid', 1])
def test_wallet_id_must_be_uuid(wallet_id, now):
    with pytest.raises(TypeError):
        WalletBalance.create(wallet_id=wallet_id, now=now)


@pytest.mark.parametrize('field', ['created_at', 'updated_at'])
def test_naive_timestamp_rejected_on_restore(balance, now, field):
    with pytest.raises(InvalidWalletBalanceError):
        WalletBalance(**{**vars(balance), field: now.replace(tzinfo=None)})


@pytest.mark.parametrize('method', ['credit', 'debit'])
@pytest.mark.parametrize('invalid_type', [False, True])
def test_invalid_time_never_mutates(balance, now, method, invalid_type):
    before = vars(balance).copy()
    error = TypeError if invalid_type else InvalidWalletBalanceError
    invalid_time = None if invalid_type else now.replace(tzinfo=None)
    with pytest.raises(error):
        getattr(balance, method)(1, now=invalid_time)
    assert vars(balance) == before

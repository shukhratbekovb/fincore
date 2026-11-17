from dataclasses import FrozenInstanceError, replace
from datetime import timedelta, timezone
from uuid import uuid4

import pytest

from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_account.enums import AccountStatus, AccountType
from backend.domain.ledger_account.errors import InvalidLedgerAccountError, LedgerAccountClosedError
from backend.domain.ledger_account.value_objects import LedgerAccountCode
from backend.domain.share.enums import CurrencyEnum


@pytest.fixture
def account(now):
    return LedgerAccount.for_wallet(wallet_id=uuid4(), currency=CurrencyEnum.USD, now=now)


@pytest.mark.parametrize('currency', list(CurrencyEnum))
def test_wallet_factory_creates_liability(currency, now):
    wallet_id = uuid4()
    account = LedgerAccount.for_wallet(wallet_id=wallet_id, currency=currency, now=now)
    assert account.wallet_id == wallet_id
    assert account.code.value == f'WALLET:{wallet_id}:{currency.value}'
    assert account.account_type == AccountType.LIABILITY
    assert account.currency == currency
    assert account.created_at == now
    assert account.status == AccountStatus.ACTIVE
    account.ensure_active()


@pytest.mark.parametrize('currency', list(CurrencyEnum))
def test_system_factory_creates_asset(currency, now):
    account = LedgerAccount.for_sandbox_funding(currency=currency, now=now)
    assert account.wallet_id is None
    assert account.code.value == f'SYS:SIM_FUNDING:{currency.value}'
    assert account.account_type == AccountType.ASSET
    assert account.currency == currency
    assert account.created_at == now
    assert account.is_active()


@pytest.mark.parametrize('system', [False, True])
def test_close_is_terminal_idempotent_and_preserves_account_identity(account, now, system):
    if system:
        account = LedgerAccount.for_sandbox_funding(currency=CurrencyEnum.USD, now=now)
    before = vars(account).copy()
    account.close()
    assert account.status == AccountStatus.CLOSED
    assert vars(account) == {**before, 'status': AccountStatus.CLOSED}
    account.close()
    with pytest.raises(LedgerAccountClosedError):
        account.ensure_active()
    with pytest.raises(FrozenInstanceError):
        account.status = AccountStatus.ACTIVE
    assert account.status == AccountStatus.CLOSED


@pytest.mark.parametrize('field', ['id', 'code', 'account_type', 'currency', 'wallet_id', 'created_at'])
def test_accounting_identity_is_read_only(account, field):
    before = vars(account).copy()
    with pytest.raises(FrozenInstanceError):
        setattr(account, field, None)
    assert vars(account) == before


def test_account_is_not_hashable_because_status_can_change(account):
    with pytest.raises(TypeError):
        hash(account)


def test_restore_closed_account(account):
    restored = LedgerAccount(**{**vars(account), 'status': AccountStatus.CLOSED})
    assert restored.id == account.id
    assert restored.code == account.code
    with pytest.raises(LedgerAccountClosedError):
        restored.ensure_active()


@pytest.mark.parametrize(('field', 'value'), [
    ('id', 'not-a-uuid'), ('wallet_id', 'not-a-uuid'), ('code', 'SYS:SIM_FUNDING:USD'),
    ('account_type', 'liability'), ('currency', 'USD'), ('status', 'active'), ('created_at', None),
])
def test_constructor_rejects_invalid_types(account, field, value):
    with pytest.raises(TypeError):
        LedgerAccount(**{**vars(account), field: value})


def test_naive_time_is_rejected(account, now):
    with pytest.raises(InvalidLedgerAccountError):
        replace(account, created_at=now.replace(tzinfo=None))


def test_aware_non_utc_time_is_accepted(now):
    local = now.astimezone(timezone(timedelta(hours=5)))
    account = LedgerAccount.for_sandbox_funding(currency=CurrencyEnum.USD, now=local)
    assert account.created_at == now


@pytest.mark.parametrize('change', ['asset_wallet', 'wrong_wallet', 'wrong_currency', 'system_code'])
def test_wallet_account_rejects_inconsistent_restored_state(account, change):
    changes = {
        'asset_wallet': {'account_type': AccountType.ASSET},
        'wrong_wallet': {'wallet_id': uuid4()},
        'wrong_currency': {'currency': CurrencyEnum.EUR},
        'system_code': {'code': LedgerAccountCode('SYS:SIM_FUNDING:USD')},
    }
    with pytest.raises(InvalidLedgerAccountError):
        replace(account, **changes[change])


@pytest.mark.parametrize('change', ['liability_system', 'wrong_currency', 'unknown_system'])
def test_system_account_rejects_inconsistent_restored_state(now, change):
    account = LedgerAccount.for_sandbox_funding(currency=CurrencyEnum.USD, now=now)
    changes = {
        'liability_system': {'account_type': AccountType.LIABILITY},
        'wrong_currency': {'currency': CurrencyEnum.EUR},
        'unknown_system': {'code': LedgerAccountCode('SYS:OTHER:USD')},
    }
    with pytest.raises(InvalidLedgerAccountError):
        replace(account, **changes[change])


@pytest.mark.parametrize('wallet_id', [None, 'uuid', 1])
def test_wallet_factory_requires_uuid(wallet_id, now):
    with pytest.raises(TypeError):
        LedgerAccount.for_wallet(wallet_id=wallet_id, currency=CurrencyEnum.USD, now=now)


@pytest.mark.parametrize('factory', ['wallet', 'system'])
def test_factories_require_currency_enum(factory, now):
    with pytest.raises(TypeError):
        if factory == 'wallet':
            LedgerAccount.for_wallet(wallet_id=uuid4(), currency='USD', now=now)
        else:
            LedgerAccount.for_sandbox_funding(currency='USD', now=now)


def test_multiple_instances_have_distinct_ids_but_stable_system_code(now):
    first = LedgerAccount.for_sandbox_funding(currency=CurrencyEnum.USD, now=now)
    second = LedgerAccount.for_sandbox_funding(currency=CurrencyEnum.USD, now=now)
    assert first.id != second.id
    assert first.code == second.code
    # Uniqueness of stored accounts requires a database constraint, not a factory.

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta, timezone
from uuid import uuid4

import pytest

from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_account.errors import LedgerAccountClosedError
from backend.domain.ledger_entry.entities import LedgerEntry, MAX_LEDGER_ENTRY_AMOUNT_MINOR
from backend.domain.ledger_entry.enums import LedgerEntrySideEnum
from backend.domain.ledger_entry.errors import InvalidLedgerEntryError
from backend.domain.share.enums import CurrencyEnum


@pytest.fixture
def account(now):
    return LedgerAccount.for_wallet(wallet_id=uuid4(), currency=CurrencyEnum.USD, now=now)


@pytest.fixture
def entry(account, now):
    return LedgerEntry.create(
        ledger_transaction_id=uuid4(),
        account=account,
        side=LedgerEntrySideEnum.DEBIT,
        amount_minor=100,
        currency=CurrencyEnum.USD,
        now=now,
    )


@pytest.mark.parametrize('side', list(LedgerEntrySideEnum))
@pytest.mark.parametrize('amount', [1, MAX_LEDGER_ENTRY_AMOUNT_MINOR])
@pytest.mark.parametrize('currency', list(CurrencyEnum))
def test_factory_preserves_line_identity_amount_and_time(now, side, amount, currency):
    account = LedgerAccount.for_wallet(wallet_id=uuid4(), currency=currency, now=now)
    transaction_id = uuid4()
    entry = LedgerEntry.create(
        ledger_transaction_id=transaction_id, account=account, side=side,
        amount_minor=amount, currency=currency, now=now,
    )
    assert entry.ledger_transaction_id == transaction_id
    assert entry.ledger_account_id == account.id
    assert entry.side is side
    assert entry.amount_minor == amount
    assert entry.currency is currency
    assert entry.created_at == now
    assert replace(entry) == entry


@pytest.mark.parametrize('amount', [0, -1, True, False, 1.5, '100', None, MAX_LEDGER_ENTRY_AMOUNT_MINOR + 1])
def test_invalid_amount_is_rejected(entry, amount):
    with pytest.raises(InvalidLedgerEntryError):
        replace(entry, amount_minor=amount)


@pytest.mark.parametrize(('field', 'value'), [
    ('id', None), ('ledger_transaction_id', 'uuid'), ('ledger_account_id', 1),
    ('side', 'debit'), ('currency', 'USD'),
])
def test_invalid_identity_and_enum_types_are_rejected(entry, field, value):
    with pytest.raises(TypeError):
        replace(entry, **{field: value})


@pytest.mark.parametrize('invalid_type', [False, True])
def test_invalid_timestamp_is_rejected(entry, now, invalid_type):
    with pytest.raises(InvalidLedgerEntryError):
        replace(entry, created_at=None if invalid_type else now.replace(tzinfo=None))


def test_non_utc_aware_time_is_accepted(entry, now):
    local_time = now.astimezone(timezone(timedelta(hours=5)))
    assert replace(entry, created_at=local_time).created_at == now


@pytest.mark.parametrize(('change', 'error'), [
    ('closed', LedgerAccountClosedError), ('currency', InvalidLedgerEntryError),
    ('account_type', TypeError), ('currency_type', TypeError),
])
def test_factory_rejects_invalid_posting_account(account, now, change, error):
    currency = CurrencyEnum.USD
    if change == 'closed':
        account.close()
    elif change == 'currency':
        currency = CurrencyEnum.EUR
    elif change == 'account_type':
        account = None
    else:
        currency = 'USD'
    with pytest.raises(error):
        LedgerEntry.create(
            ledger_transaction_id=uuid4(), account=account,
            side=LedgerEntrySideEnum.DEBIT, amount_minor=100, currency=currency, now=now,
        )


@pytest.mark.parametrize('field', [
    'id', 'ledger_transaction_id', 'ledger_account_id', 'side', 'amount_minor', 'currency', 'created_at',
])
def test_posted_entry_is_immutable(entry, field):
    with pytest.raises(FrozenInstanceError):
        setattr(entry, field, None)


def test_historical_entry_can_be_restored_after_account_closure(entry, account):
    account.close()
    assert replace(entry) == entry


def test_each_entry_has_unique_identity(entry):
    other = replace(entry, id=uuid4())
    assert entry.id != other.id

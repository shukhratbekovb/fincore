from dataclasses import FrozenInstanceError, replace
from datetime import timedelta, timezone
from uuid import uuid4

import pytest

from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_account.errors import LedgerAccountClosedError
from backend.domain.ledger_entry.entities import MAX_LEDGER_ENTRY_AMOUNT_MINOR
from backend.domain.ledger_entry.enums import LedgerEntrySideEnum
from backend.domain.ledger_entry.errors import InvalidLedgerEntryError
from backend.domain.ledger_transaction.entities import LedgerTransaction
from backend.domain.ledger_transaction.enums import LedgerTransactionKindEnum
from backend.domain.ledger_transaction.errors import InvalidLedgerTransactionError, UnbalancedLedgerTransactionError
from backend.domain.sandbox_top_up.entities import SandboxTopUp
from backend.domain.sandbox_top_up.enums import SandboxTopUpRejectionCodeEnum
from backend.domain.sandbox_top_up.errors import InvalidSandboxTopUpAmountError
from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.entities import Transfer
from backend.domain.transfer.enums import TransferRejectionCodeEnum
from backend.domain.transfer.errors import InvalidTransferAmountError


@pytest.fixture
def transfer(now):
    operation = Transfer.create(
        sender_wallet_id=uuid4(), receiver_wallet_id=uuid4(), amount_minor=100,
        currency=CurrencyEnum.USD, now=now,
    )
    operation.complete(now=now)
    return operation


@pytest.fixture
def top_up(now):
    operation = SandboxTopUp.create(
        wallet_id=uuid4(), initiated_by_user_id=uuid4(), amount_minor=100,
        currency=CurrencyEnum.USD, now=now,
    )
    operation.complete(now=now)
    return operation


@pytest.fixture
def sender_account(transfer, now):
    return LedgerAccount.for_wallet(wallet_id=transfer.sender_wallet_id, currency=transfer.currency, now=now)


@pytest.fixture
def receiver_account(transfer, now):
    return LedgerAccount.for_wallet(wallet_id=transfer.receiver_wallet_id, currency=transfer.currency, now=now)


@pytest.fixture
def journal(transfer, sender_account, receiver_account, now):
    return LedgerTransaction.for_transfer(
        transfer=transfer, sender_account=sender_account, receiver_account=receiver_account, now=now,
    )


@pytest.fixture
def funding_account(top_up, now):
    return LedgerAccount.for_sandbox_funding(currency=top_up.currency, now=now)


@pytest.fixture
def wallet_account(top_up, now):
    return LedgerAccount.for_wallet(wallet_id=top_up.wallet_id, currency=top_up.currency, now=now)


def test_transfer_posts_sender_debit_receiver_credit(journal, transfer, sender_account, receiver_account, now):
    assert journal.kind is LedgerTransactionKindEnum.P2P_TRANSFER
    assert journal.transfer_id == transfer.id
    assert journal.sandbox_top_up_id is None
    assert journal.currency is transfer.currency
    assert journal.posted_at == now
    debit, credit = journal.entries
    assert debit.side is LedgerEntrySideEnum.DEBIT
    assert credit.side is LedgerEntrySideEnum.CREDIT
    assert debit.ledger_account_id == sender_account.id
    assert credit.ledger_account_id == receiver_account.id
    assert debit.amount_minor == credit.amount_minor == transfer.amount_minor
    assert debit.ledger_transaction_id == credit.ledger_transaction_id == journal.id
    assert debit.created_at == credit.created_at == journal.posted_at
    assert replace(journal) == journal


def test_sandbox_posts_funding_debit_wallet_credit(top_up, funding_account, wallet_account, now):
    before = vars(top_up).copy()
    journal = LedgerTransaction.for_sandbox_top_up(
        top_up=top_up, funding_account=funding_account, wallet_account=wallet_account,
        now=now, reference='sandbox-test',
    )
    assert journal.kind is LedgerTransactionKindEnum.SANDBOX_TOPUP
    assert journal.sandbox_top_up_id == top_up.id
    assert journal.transfer_id is None
    assert journal.reference == 'sandbox-test'
    debit, credit = journal.entries
    assert debit.side is LedgerEntrySideEnum.DEBIT
    assert credit.side is LedgerEntrySideEnum.CREDIT
    assert debit.ledger_account_id == funding_account.id
    assert credit.ledger_account_id == wallet_account.id
    assert debit.amount_minor == credit.amount_minor == top_up.amount_minor
    assert vars(top_up) == before


@pytest.mark.parametrize('currency', list(CurrencyEnum))
def test_factories_support_all_currencies(transfer, top_up, now, currency):
    transfer = replace(transfer, currency=currency)
    top_up = replace(top_up, currency=currency)
    journal = LedgerTransaction.for_transfer(
        transfer=transfer,
        sender_account=LedgerAccount.for_wallet(wallet_id=transfer.sender_wallet_id, currency=currency, now=now),
        receiver_account=LedgerAccount.for_wallet(wallet_id=transfer.receiver_wallet_id, currency=currency, now=now),
        now=now,
    )
    funding = LedgerTransaction.for_sandbox_top_up(
        top_up=top_up,
        funding_account=LedgerAccount.for_sandbox_funding(currency=currency, now=now),
        wallet_account=LedgerAccount.for_wallet(wallet_id=top_up.wallet_id, currency=currency, now=now),
        now=now,
    )
    assert all(entry.currency is currency for entry in journal.entries + funding.entries)


@pytest.mark.parametrize('field', [
    'id', 'kind', 'currency', 'posted_at', 'entries', 'transfer_id', 'sandbox_top_up_id', 'reference',
])
def test_journal_is_immutable(journal, field):
    with pytest.raises(FrozenInstanceError):
        setattr(journal, field, None)


def test_balanced_multi_entry_journal_is_allowed(journal):
    debit, credit = journal.entries
    extra_debit = replace(debit, id=uuid4(), ledger_account_id=uuid4(), amount_minor=50)
    extra_credit = replace(credit, id=uuid4(), ledger_account_id=uuid4(), amount_minor=50)
    restored = replace(journal, entries=(*journal.entries, extra_debit, extra_credit))
    assert len(restored.entries) == 4


def test_totals_may_exceed_bigint_when_each_entry_is_valid(journal):
    debit, credit = journal.entries
    debit = replace(debit, amount_minor=MAX_LEDGER_ENTRY_AMOUNT_MINOR)
    credit = replace(credit, amount_minor=MAX_LEDGER_ENTRY_AMOUNT_MINOR)
    extra_debit = replace(debit, id=uuid4(), ledger_account_id=uuid4())
    extra_credit = replace(credit, id=uuid4(), ledger_account_id=uuid4())
    restored = replace(journal, entries=(debit, credit, extra_debit, extra_credit))
    assert sum(entry.amount_minor for entry in restored.entries) == 4 * MAX_LEDGER_ENTRY_AMOUNT_MINOR


@pytest.mark.parametrize(('field', 'value'), [
    ('id', None), ('transfer_id', 'uuid'), ('sandbox_top_up_id', 1),
    ('kind', 'p2p_transfer'), ('currency', 'USD'),
])
def test_invalid_types_are_rejected(journal, field, value):
    with pytest.raises(TypeError):
        replace(journal, **{field: value})


@pytest.mark.parametrize('change', ['no_source', 'both_sources', 'wrong_kind_transfer', 'wrong_kind_top_up'])
def test_source_is_exclusive_and_matches_kind(journal, change):
    changes = {
        'no_source': {'transfer_id': None},
        'both_sources': {'sandbox_top_up_id': uuid4()},
        'wrong_kind_transfer': {'kind': LedgerTransactionKindEnum.SANDBOX_TOPUP},
        'wrong_kind_top_up': {'transfer_id': None, 'sandbox_top_up_id': uuid4()},
    }[change]
    with pytest.raises(InvalidLedgerTransactionError):
        replace(journal, **changes)


@pytest.mark.parametrize('reference', ['', ' ', 'x' * 129, 1])
def test_invalid_reference_is_rejected(journal, reference):
    with pytest.raises(InvalidLedgerTransactionError):
        replace(journal, reference=reference)


@pytest.mark.parametrize('reference', [None, 'receipt-42', 'x' * 128])
def test_valid_reference_is_preserved(journal, reference):
    assert replace(journal, reference=reference).reference == reference


@pytest.mark.parametrize('entries_kind', ['empty', 'one', 'list', 'invalid_type'])
def test_journal_requires_two_immutable_entries(journal, entries_kind):
    entries = {
        'empty': (), 'one': journal.entries[:1], 'list': list(journal.entries), 'invalid_type': None,
    }[entries_kind]
    with pytest.raises(InvalidLedgerTransactionError):
        replace(journal, entries=entries)


def test_journal_rejects_non_entry_objects(journal):
    with pytest.raises(TypeError):
        replace(journal, entries=(journal.entries[0], None))


@pytest.mark.parametrize('change', ['transaction', 'currency', 'time', 'duplicate_id', 'duplicate_account_side'])
def test_entry_links_and_uniqueness_are_checked(journal, now, change):
    debit, credit = journal.entries
    changes = {
        'transaction': {'ledger_transaction_id': uuid4()},
        'currency': {'currency': CurrencyEnum.EUR},
        'time': {'created_at': now + timedelta(seconds=1)},
        'duplicate_id': {'id': debit.id},
        'duplicate_account_side': {'ledger_account_id': debit.ledger_account_id, 'side': debit.side},
    }[change]
    with pytest.raises(InvalidLedgerTransactionError):
        replace(journal, entries=(debit, replace(credit, **changes)))


@pytest.mark.parametrize('change', ['amount', 'all_debit', 'all_credit'])
def test_unbalanced_journal_is_rejected(journal, change):
    debit, credit = journal.entries
    if change == 'amount':
        credit = replace(credit, amount_minor=99)
    elif change == 'all_debit':
        credit = replace(credit, side=LedgerEntrySideEnum.DEBIT)
    else:
        debit = replace(debit, side=LedgerEntrySideEnum.CREDIT)
    with pytest.raises(UnbalancedLedgerTransactionError):
        replace(journal, entries=(debit, credit))


@pytest.mark.parametrize('invalid_type', [False, True])
def test_restored_posting_requires_aware_time(journal, now, invalid_type):
    with pytest.raises(InvalidLedgerTransactionError):
        replace(journal, posted_at=None if invalid_type else now.replace(tzinfo=None))


def test_equivalent_timezone_is_accepted(journal, now):
    local_time = now.astimezone(timezone(timedelta(hours=5)))
    assert replace(journal, posted_at=local_time).posted_at == now


@pytest.mark.parametrize('state', ['pending', 'rejected'])
def test_transfer_journal_rejects_uncompleted_source(transfer, sender_account, receiver_account, now, state):
    transfer = replace(transfer, status=type(transfer.status).PENDING, completed_at=None)
    if state == 'rejected':
        transfer.reject(TransferRejectionCodeEnum.INSUFFICIENT_FUNDS, now=now)
    before = vars(transfer).copy()
    with pytest.raises(InvalidLedgerTransactionError):
        LedgerTransaction.for_transfer(
            transfer=transfer, sender_account=sender_account, receiver_account=receiver_account, now=now,
        )
    assert vars(transfer) == before


@pytest.mark.parametrize('state', ['pending', 'rejected'])
def test_top_up_journal_rejects_uncompleted_source(top_up, funding_account, wallet_account, now, state):
    top_up = replace(top_up, status=type(top_up.status).PENDING, completed_at=None)
    if state == 'rejected':
        top_up.reject(SandboxTopUpRejectionCodeEnum.WALLET_NOT_ACTIVE, now=now)
    with pytest.raises(InvalidLedgerTransactionError):
        LedgerTransaction.for_sandbox_top_up(
            top_up=top_up, funding_account=funding_account, wallet_account=wallet_account, now=now,
        )


@pytest.mark.parametrize('source_type', ['transfer', 'top_up'])
def test_source_must_have_expected_type(sender_account, receiver_account, funding_account, wallet_account, now, source_type):
    with pytest.raises(TypeError):
        if source_type == 'transfer':
            LedgerTransaction.for_transfer(
                transfer=None, sender_account=sender_account, receiver_account=receiver_account, now=now,
            )
        else:
            LedgerTransaction.for_sandbox_top_up(
                top_up=None, funding_account=funding_account, wallet_account=wallet_account, now=now,
            )


@pytest.mark.parametrize('account_name', ['sender', 'receiver'])
@pytest.mark.parametrize('change', ['wrong_type', 'wrong_wallet', 'currency', 'closed'])
def test_transfer_posting_checks_accounts(transfer, sender_account, receiver_account, now, account_name, change):
    account = sender_account if account_name == 'sender' else receiver_account
    error = InvalidLedgerTransactionError
    if change == 'wrong_type':
        account = None
        error = TypeError
    elif change == 'wrong_wallet':
        account = LedgerAccount.for_wallet(wallet_id=uuid4(), currency=transfer.currency, now=now)
    elif change == 'currency':
        account = LedgerAccount.for_wallet(wallet_id=account.wallet_id, currency=CurrencyEnum.EUR, now=now)
        error = InvalidLedgerEntryError
    else:
        account.close()
        error = LedgerAccountClosedError
    before = vars(transfer).copy()
    with pytest.raises(error):
        LedgerTransaction.for_transfer(
            transfer=transfer, sender_account=account if account_name == 'sender' else sender_account,
            receiver_account=account if account_name == 'receiver' else receiver_account, now=now,
        )
    assert vars(transfer) == before


@pytest.mark.parametrize('account_name', ['funding', 'wallet'])
@pytest.mark.parametrize('change', ['wrong_type', 'wrong_purpose', 'currency', 'closed'])
def test_top_up_posting_checks_accounts(top_up, funding_account, wallet_account, now, account_name, change):
    account = funding_account if account_name == 'funding' else wallet_account
    error = InvalidLedgerTransactionError
    if change == 'wrong_type':
        account = None
        error = TypeError
    elif change == 'wrong_purpose':
        account = LedgerAccount.for_wallet(wallet_id=uuid4(), currency=top_up.currency, now=now)
    elif change == 'currency':
        account = (
            LedgerAccount.for_sandbox_funding(currency=CurrencyEnum.EUR, now=now)
            if account_name == 'funding' else
            LedgerAccount.for_wallet(wallet_id=top_up.wallet_id, currency=CurrencyEnum.EUR, now=now)
        )
        error = InvalidLedgerEntryError
    else:
        account.close()
        error = LedgerAccountClosedError
    with pytest.raises(error):
        LedgerTransaction.for_sandbox_top_up(
            top_up=top_up, funding_account=account if account_name == 'funding' else funding_account,
            wallet_account=account if account_name == 'wallet' else wallet_account, now=now,
        )


@pytest.mark.parametrize('time_kind', ['naive', 'invalid_type', 'before_completion'])
def test_posting_time_cannot_be_invalid_or_precede_completion(transfer, sender_account, receiver_account, now, time_kind):
    value = {
        'naive': now.replace(tzinfo=None), 'invalid_type': None,
        'before_completion': now - timedelta(seconds=1),
    }[time_kind]
    with pytest.raises(InvalidLedgerTransactionError):
        LedgerTransaction.for_transfer(
            transfer=transfer, sender_account=sender_account, receiver_account=receiver_account, now=value,
        )


def test_factory_revalidates_mutable_transfer(transfer, sender_account, receiver_account, now):
    transfer.amount_minor = 0
    with pytest.raises(InvalidTransferAmountError):
        LedgerTransaction.for_transfer(
            transfer=transfer, sender_account=sender_account, receiver_account=receiver_account, now=now,
        )


def test_factory_revalidates_mutable_top_up(top_up, funding_account, wallet_account, now):
    top_up.amount_minor = 0
    with pytest.raises(InvalidSandboxTopUpAmountError):
        LedgerTransaction.for_sandbox_top_up(
            top_up=top_up, funding_account=funding_account, wallet_account=wallet_account, now=now,
        )

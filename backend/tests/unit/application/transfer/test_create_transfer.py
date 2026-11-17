from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from backend.application.auth.errors import UserInactiveError
from backend.application.idempotency.dtos import IdempotencyRecord
from backend.application.idempotency.errors import (
    IdempotencyConflictError, IdempotencyInProgressError, InvalidIdempotencyKeyError,
)
from backend.application.transfer.dtos.create_transfer import CreateTransferCommand
from backend.application.transfer.errors import TransferCurrencyMismatchError, TransferLimitExceededError
from backend.application.transfer.use_cases import create_transfer as transfer_module
from backend.application.transfer.use_cases.create_transfer import CreateTransferUseCase, TRANSFER_IDEMPOTENCY_SCOPE
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.errors import WalletAccountingStateError, WalletNotFoundError
from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_account.errors import LedgerAccountClosedError
from backend.domain.ledger_entry.enums import LedgerEntrySideEnum
from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.entities import MAX_TRANSFER_AMOUNT_MINOR
from backend.domain.transfer.enums import TransferStatusEnum
from backend.domain.transfer.errors import InvalidTransferAmountError, SameWalletTransferError
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, Username
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.errors import WalletNotActiveError
from backend.domain.wallet.value_objects import WalletName, WalletNumber
from backend.domain.wallet_balance.entities import MAX_BALANCE_MINOR, WalletBalance
from backend.domain.wallet_balance.errors import InsufficientFundsError, WalletBalanceOverflowError


@pytest.fixture
def ctx(now):
    user = User.register(Username('alice'), Email('alice@example.com'))
    user.activate()
    sender = Wallet(
        id=UUID(int=20), user_id=user.id, name=WalletName('Sender'),
        number=WalletNumber('1' * 20), currency=CurrencyEnum.USD,
    )
    receiver = Wallet(
        id=UUID(int=10), user_id=uuid4(), name=WalletName('Receiver'),
        number=WalletNumber('2' * 20), currency=CurrencyEnum.USD,
    )
    wallets = {sender.id: sender, receiver.id: receiver}
    balances = {
        sender.id: WalletBalance(wallet_id=sender.id, posted_minor=50000, created_at=now, updated_at=now),
        receiver.id: WalletBalance(wallet_id=receiver.id, posted_minor=2000, created_at=now, updated_at=now),
    }
    accounts = {
        wallet.id: LedgerAccount.for_wallet(wallet_id=wallet.id, currency=wallet.currency, now=now)
        for wallet in wallets.values()
    }
    events = []

    def read(group, values):
        def get(wallet_id):
            events.append((group, wallet_id))
            return values.get(wallet_id)
        return get

    uow = AsyncMock()
    uow.users = SimpleNamespace(
        get_by_id=AsyncMock(return_value=user),
        get_by_id_for_update=AsyncMock(return_value=user),
    )
    uow.wallets = SimpleNamespace(
        get_by_id_for_update=AsyncMock(side_effect=read('wallet', wallets)), save=AsyncMock(),
    )
    uow.wallet_balances = SimpleNamespace(
        get_by_wallet_id_for_update=AsyncMock(side_effect=read('balance', balances)), save=AsyncMock(),
    )
    uow.ledger_accounts = SimpleNamespace(
        get_by_wallet_id_for_update=AsyncMock(side_effect=read('account', accounts)), save=AsyncMock(),
    )
    uow.transfers = SimpleNamespace(add=AsyncMock())
    uow.ledger_transactions = SimpleNamespace(add=AsyncMock())
    uow.idempotency = SimpleNamespace(claim=AsyncMock(return_value=None), complete=AsyncMock())

    def read_clock():
        events.append(('clock', None))
        return now

    clock = SimpleNamespace(now=Mock(side_effect=read_clock))
    command = CreateTransferCommand(
        user_id=user.id, sender_wallet_id=sender.id, receiver_wallet_id=receiver.id,
        amount_minor=10000, currency=CurrencyEnum.USD, idempotency_key='transfer-request-1',
    )
    return SimpleNamespace(
        uow=uow, user=user, sender=sender, receiver=receiver, wallets=wallets,
        balances=balances, accounts=accounts, events=events, clock=clock, command=command,
        use_case=CreateTransferUseCase(uow=uow, clock=clock),
    )


def assert_no_financial_writes(ctx):
    ctx.uow.transfers.add.assert_not_awaited()
    ctx.uow.ledger_transactions.add.assert_not_awaited()
    ctx.uow.wallet_balances.save.assert_not_awaited()
    ctx.uow.idempotency.complete.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


async def test_transfer_posts_one_balanced_journal_and_updates_both_projections(ctx, now):
    result = await ctx.use_case.execute(cmd=ctx.command)
    transfer = ctx.uow.transfers.add.await_args.args[0]
    journal = ctx.uow.ledger_transactions.add.await_args.args[0]
    saved = {call.args[0].wallet_id: call.args[0] for call in ctx.uow.wallet_balances.save.await_args_list}
    assert result.transfer_id == transfer.id == journal.transfer_id
    assert transfer.status is TransferStatusEnum.COMPLETED
    assert transfer.created_at == transfer.updated_at == transfer.completed_at == journal.posted_at == now
    assert saved[ctx.sender.id].posted_minor == 40000
    assert saved[ctx.receiver.id].posted_minor == 12000
    assert sum(balance.posted_minor for balance in saved.values()) == 52000
    assert all(balance.version == 1 and balance.updated_at == now for balance in saved.values())
    assert len(journal.entries) == 2
    debit, credit = journal.entries
    assert debit.side is LedgerEntrySideEnum.DEBIT
    assert credit.side is LedgerEntrySideEnum.CREDIT
    assert debit.ledger_account_id == ctx.accounts[ctx.sender.id].id
    assert credit.ledger_account_id == ctx.accounts[ctx.receiver.id].id
    assert debit.amount_minor == credit.amount_minor == ctx.command.amount_minor
    assert debit.ledger_transaction_id == credit.ledger_transaction_id == journal.id
    ctx.uow.transfers.add.assert_awaited_once()
    ctx.uow.ledger_transactions.add.assert_awaited_once()
    ctx.uow.commit.assert_awaited_once()
    ctx.uow.wallets.save.assert_not_awaited()
    ctx.uow.ledger_accounts.save.assert_not_awaited()


@pytest.mark.parametrize('reverse', [False, True])
async def test_all_locks_follow_wallet_balance_account_order_with_clock_last(ctx, reverse):
    if reverse:
        ctx.receiver.user_id = ctx.user.id
        ctx.balances[ctx.receiver.id].posted_minor = 50000
        ctx.command = replace(ctx.command, sender_wallet_id=ctx.receiver.id, receiver_wallet_id=ctx.sender.id)
    await ctx.use_case.execute(ctx.command)
    ids = sorted(ctx.wallets)
    assert ctx.events == [
        (group, wallet_id) for group in ('wallet', 'balance', 'account') for wallet_id in ids
    ] + [('clock', None)]


async def test_transfer_between_own_wallets_is_allowed(ctx):
    ctx.receiver.user_id = ctx.user.id
    result = await ctx.use_case.execute(ctx.command)
    assert result.transfer_id is not None
    ctx.uow.commit.assert_awaited_once()


async def test_spending_entire_balance_is_allowed(ctx):
    await ctx.use_case.execute(replace(ctx.command, amount_minor=50000))
    saved = {call.args[0].wallet_id: call.args[0] for call in ctx.uow.wallet_balances.save.await_args_list}
    assert saved[ctx.sender.id].posted_minor == 0


@pytest.mark.parametrize('amount', [0, -1, True, False, 1.5, '100', None, MAX_TRANSFER_AMOUNT_MINOR + 1])
async def test_invalid_amount_rejected_before_uow(ctx, amount):
    with pytest.raises(InvalidTransferAmountError):
        await ctx.use_case.execute(replace(ctx.command, amount_minor=amount))
    ctx.uow.__aenter__.assert_not_awaited()
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('key', ['', ' ', 'has space', 'line\nbreak', '\t', 'ключ', 'x' * 256, None, 1])
async def test_invalid_idempotency_key_rejected_before_uow(ctx, key):
    with pytest.raises(InvalidIdempotencyKeyError):
        await ctx.use_case.execute(replace(ctx.command, idempotency_key=key))
    ctx.uow.__aenter__.assert_not_awaited()


@pytest.mark.parametrize(('field', 'value'), [
    ('user_id', None), ('sender_wallet_id', 'uuid'), ('receiver_wallet_id', 1), ('currency', 'USD'),
])
async def test_invalid_id_and_currency_types_rejected_before_uow(ctx, field, value):
    with pytest.raises(TypeError):
        await ctx.use_case.execute(replace(ctx.command, **{field: value}))
    ctx.uow.__aenter__.assert_not_awaited()


async def test_same_wallet_rejected_before_uow(ctx):
    with pytest.raises(SameWalletTransferError):
        await ctx.use_case.execute(replace(ctx.command, receiver_wallet_id=ctx.sender.id))
    ctx.uow.__aenter__.assert_not_awaited()


@pytest.mark.parametrize('stage', ['read', 'lock'])
@pytest.mark.parametrize('status', [None, UserStatusEnum.PENDING_CONFIRMATION, UserStatusEnum.SUSPENDED, UserStatusEnum.CLOSED])
async def test_missing_or_inactive_actor_cannot_transfer(ctx, stage, status):
    user = None if status is None else replace(ctx.user, status=status)
    method = ctx.uow.users.get_by_id if stage == 'read' else ctx.uow.users.get_by_id_for_update
    method.return_value = user
    with pytest.raises(UserNotFoundError if status is None else UserInactiveError):
        await ctx.use_case.execute(ctx.command)
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    if stage == 'read':
        ctx.uow.idempotency.claim.assert_not_awaited()
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('which', ['sender', 'receiver'])
@pytest.mark.parametrize('change', ['missing', 'wrong_id'])
async def test_missing_or_wrong_wallet_is_not_found(ctx, which, change):
    wallet = getattr(ctx, which)
    ctx.wallets[wallet.id] = None if change == 'missing' else replace(wallet, id=uuid4())
    with pytest.raises(WalletNotFoundError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


async def test_foreign_sender_is_not_found(ctx):
    ctx.sender.user_id = uuid4()
    with pytest.raises(WalletNotFoundError):
        await ctx.use_case.execute(ctx.command)
    ctx.uow.wallet_balances.get_by_wallet_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('which', ['sender', 'receiver'])
@pytest.mark.parametrize('status', [WalletStatusEnum.FROZEN, WalletStatusEnum.CLOSED])
async def test_both_wallets_must_be_active(ctx, which, status):
    getattr(ctx, which).status = status
    with pytest.raises(WalletNotActiveError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('which', ['sender', 'receiver', 'command'])
async def test_both_currencies_must_match_command(ctx, which):
    if which == 'command':
        ctx.command = replace(ctx.command, currency=CurrencyEnum.EUR)
    else:
        getattr(ctx, which).currency = CurrencyEnum.EUR
    with pytest.raises(TransferCurrencyMismatchError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('which', ['sender', 'receiver'])
@pytest.mark.parametrize('change', ['missing_balance', 'wrong_balance', 'missing_account', 'wrong_account', 'currency', 'type'])
async def test_missing_or_inconsistent_accounting_state_never_posts(ctx, now, which, change):
    wallet = getattr(ctx, which)
    if change == 'missing_balance':
        ctx.balances[wallet.id] = None
    elif change == 'wrong_balance':
        ctx.balances[wallet.id] = replace(ctx.balances[wallet.id], wallet_id=uuid4())
    elif change == 'missing_account':
        ctx.accounts[wallet.id] = None
    elif change == 'wrong_account':
        ctx.accounts[wallet.id] = LedgerAccount.for_wallet(wallet_id=uuid4(), currency=wallet.currency, now=now)
    elif change == 'currency':
        ctx.accounts[wallet.id] = LedgerAccount.for_wallet(wallet_id=wallet.id, currency=CurrencyEnum.EUR, now=now)
    else:
        ctx.accounts[wallet.id] = SimpleNamespace(wallet_id=wallet.id, currency=wallet.currency, account_type='asset')
    with pytest.raises(WalletAccountingStateError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('which', ['sender', 'receiver'])
async def test_closed_ledger_account_never_posts(ctx, which):
    ctx.accounts[getattr(ctx, which).id].close()
    with pytest.raises(LedgerAccountClosedError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('change', ['insufficient', 'receiver_overflow', 'sender_version', 'receiver_version'])
async def test_invalid_balance_change_preserves_repository_entities(ctx, change):
    error = WalletBalanceOverflowError
    if change == 'insufficient':
        ctx.balances[ctx.sender.id].posted_minor = 9999
        error = InsufficientFundsError
    elif change == 'receiver_overflow':
        ctx.balances[ctx.receiver.id].posted_minor = MAX_BALANCE_MINOR
    else:
        wallet_id = ctx.sender.id if change == 'sender_version' else ctx.receiver.id
        ctx.balances[wallet_id].version = MAX_BALANCE_MINOR
    before = {key: vars(balance).copy() for key, balance in ctx.balances.items()}
    with pytest.raises(error):
        await ctx.use_case.execute(ctx.command)
    assert {key: vars(balance) for key, balance in ctx.balances.items()} == before
    assert_no_financial_writes(ctx)


async def test_journal_failure_never_saves_or_mutates_repository_balances(ctx, monkeypatch):
    before = {key: vars(balance).copy() for key, balance in ctx.balances.items()}
    monkeypatch.setattr(transfer_module.LedgerTransaction, 'for_transfer', Mock(side_effect=RuntimeError('journal failed')))
    with pytest.raises(RuntimeError, match='journal failed'):
        await ctx.use_case.execute(ctx.command)
    assert {key: vars(balance) for key, balance in ctx.balances.items()} == before
    assert_no_financial_writes(ctx)
    assert ctx.uow.__aexit__.await_args.args[0] is RuntimeError


@pytest.mark.parametrize('stage', ['transfer', 'journal', 'first_balance', 'second_balance', 'replay', 'commit'])
async def test_persistence_failure_propagates_to_uow_without_returning_success(ctx, stage):
    error = RuntimeError('storage unavailable')
    if stage in ('first_balance', 'second_balance'):
        ctx.uow.wallet_balances.save.side_effect = [error] if stage == 'first_balance' else [None, error]
    else:
        operation = {
            'transfer': ctx.uow.transfers.add, 'journal': ctx.uow.ledger_transactions.add,
            'replay': ctx.uow.idempotency.complete, 'commit': ctx.uow.commit,
        }[stage]
        operation.side_effect = error
    with pytest.raises(RuntimeError, match='storage unavailable'):
        await ctx.use_case.execute(ctx.command)
    assert ctx.uow.__aexit__.await_args.args[1] is error
    if stage != 'commit':
        ctx.uow.commit.assert_not_awaited()


async def test_all_records_and_replay_saved_before_single_commit(ctx):
    events = []
    for label, operation in (
        ('transfer', ctx.uow.transfers.add), ('journal', ctx.uow.ledger_transactions.add),
        ('balance', ctx.uow.wallet_balances.save), ('replay', ctx.uow.idempotency.complete),
        ('commit', ctx.uow.commit),
    ):
        operation.side_effect = lambda *args, label=label, **kwargs: events.append(label)
    await ctx.use_case.execute(ctx.command)
    assert events == ['transfer', 'journal', 'balance', 'balance', 'replay', 'commit']


async def test_retry_returns_same_id_without_repeating_financial_work(ctx):
    first = await ctx.use_case.execute(ctx.command)
    claimed = ctx.uow.idempotency.claim.await_args.kwargs
    completed = ctx.uow.idempotency.complete.await_args.kwargs
    assert claimed == {
        'user_id': ctx.user.id, 'scope': TRANSFER_IDEMPOTENCY_SCOPE,
        'key': ctx.command.idempotency_key, 'payload_hash': completed['payload_hash'],
    }
    assert completed['resource_id'] == first.transfer_id
    assert len(claimed['payload_hash']) == 64
    ctx.uow.idempotency.claim.return_value = IdempotencyRecord(
        payload_hash=claimed['payload_hash'], resource_id=first.transfer_id,
    )
    locked_count = ctx.uow.wallets.get_by_id_for_update.await_count
    second = await ctx.use_case.execute(ctx.command)
    assert second == first
    assert ctx.uow.wallets.get_by_id_for_update.await_count == locked_count
    ctx.uow.transfers.add.assert_awaited_once()
    ctx.uow.ledger_transactions.add.assert_awaited_once()
    ctx.uow.commit.assert_awaited_once()


@pytest.mark.parametrize('field', ['amount_minor', 'sender_wallet_id', 'receiver_wallet_id', 'currency'])
async def test_same_key_with_different_payload_conflicts(ctx, field):
    old_hash = CreateTransferUseCase._payload_hash(ctx.command)
    ctx.uow.idempotency.claim.return_value = IdempotencyRecord(payload_hash=old_hash, resource_id=uuid4())
    values = {'amount_minor': 20000, 'sender_wallet_id': uuid4(), 'receiver_wallet_id': uuid4(), 'currency': CurrencyEnum.EUR}
    with pytest.raises(IdempotencyConflictError):
        await ctx.use_case.execute(replace(ctx.command, **{field: values[field]}))
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


async def test_unfinished_claim_returns_in_progress_without_financial_work(ctx):
    ctx.uow.idempotency.claim.return_value = IdempotencyRecord(
        payload_hash=CreateTransferUseCase._payload_hash(ctx.command), resource_id=None,
    )
    with pytest.raises(IdempotencyInProgressError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


async def test_claim_timeout_propagates_before_financial_locks(ctx):
    ctx.uow.idempotency.claim.side_effect = IdempotencyInProgressError()
    with pytest.raises(IdempotencyInProgressError):
        await ctx.use_case.execute(ctx.command)
    ctx.uow.users.get_by_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


async def test_new_key_with_same_payload_is_a_new_intent(ctx):
    first = await ctx.use_case.execute(ctx.command)
    second = await ctx.use_case.execute(replace(ctx.command, idempotency_key='transfer-request-2'))
    assert first.transfer_id != second.transfer_id
    assert ctx.uow.commit.await_count == 2


@pytest.mark.parametrize('limit', [0, -1, True, 1.5, MAX_TRANSFER_AMOUNT_MINOR + 1])
def test_invalid_configured_limit_is_rejected(ctx, limit):
    with pytest.raises(ValueError):
        CreateTransferUseCase(ctx.uow, ctx.clock, max_amount_minor=limit)


async def test_configured_limit_blocks_new_transfer(ctx):
    use_case = CreateTransferUseCase(ctx.uow, ctx.clock, max_amount_minor=9999)
    with pytest.raises(TransferLimitExceededError):
        await use_case.execute(ctx.command)
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


async def test_replay_survives_lowered_business_limit(ctx):
    resource_id = uuid4()
    ctx.uow.idempotency.claim.return_value = IdempotencyRecord(
        payload_hash=CreateTransferUseCase._payload_hash(ctx.command), resource_id=resource_id,
    )
    use_case = CreateTransferUseCase(ctx.uow, ctx.clock, max_amount_minor=9999)
    result = await use_case.execute(ctx.command)
    assert result.transfer_id == resource_id
    assert_no_financial_writes(ctx)

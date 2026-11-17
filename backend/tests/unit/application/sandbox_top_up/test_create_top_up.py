from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from backend.application.auth.errors import UserInactiveError
from backend.application.idempotency.dtos import IdempotencyRecord
from backend.application.idempotency.errors import (
    IdempotencyConflictError, IdempotencyInProgressError, InvalidIdempotencyKeyError,
)
from backend.application.sandbox_top_up.dtos.create_top_up import CreateSandboxTopUpCommand
from backend.application.sandbox_top_up.errors import (
    SandboxDisabledError, SandboxFundingAccountError, SandboxOperatorRequiredError,
    SandboxTopUpCurrencyMismatchError, SandboxTopUpLimitExceededError,
)
from backend.application.sandbox_top_up.use_cases import create_top_up as top_up_module
from backend.application.sandbox_top_up.use_cases.create_top_up import (
    CreateSandboxTopUpUseCase, SANDBOX_TOP_UP_IDEMPOTENCY_SCOPE,
)
from backend.application.transfer.use_cases.create_transfer import TRANSFER_IDEMPOTENCY_SCOPE
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.errors import WalletAccountingStateError, WalletNotFoundError
from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_account.enums import AccountType
from backend.domain.ledger_account.errors import LedgerAccountClosedError
from backend.domain.ledger_account.value_objects import LedgerAccountCode
from backend.domain.ledger_entry.enums import LedgerEntrySideEnum
from backend.domain.sandbox_top_up.entities import MAX_SANDBOX_TOP_UP_AMOUNT_MINOR
from backend.domain.sandbox_top_up.enums import SandboxTopUpStatusEnum
from backend.domain.sandbox_top_up.errors import InvalidSandboxTopUpAmountError
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, Username
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.errors import WalletNotActiveError
from backend.domain.wallet.value_objects import WalletName, WalletNumber
from backend.domain.wallet_balance.entities import MAX_BALANCE_MINOR, WalletBalance
from backend.domain.wallet_balance.errors import WalletBalanceOverflowError


@pytest.fixture
def ctx(now):
    user = User.register(Username('operator'), Email('operator@example.com'))
    user.activate()
    wallet = Wallet(
        user_id=uuid4(), name=WalletName('Target'), number=WalletNumber('1' * 20), currency=CurrencyEnum.USD,
    )
    balance = WalletBalance(wallet_id=wallet.id, posted_minor=2000, created_at=now, updated_at=now)
    account = LedgerAccount.for_wallet(wallet_id=wallet.id, currency=wallet.currency, now=now)
    funding = LedgerAccount.for_sandbox_funding(currency=wallet.currency, now=now)
    events = []

    def read(label, value):
        def record(*args, **kwargs):
            events.append(label)
            return value
        return record

    uow = AsyncMock()
    uow.users = SimpleNamespace(
        get_by_id=AsyncMock(return_value=user),
        get_by_id_for_update=AsyncMock(side_effect=read('user', user)),
    )
    uow.sandbox_operator_reader = SimpleNamespace(is_operator=AsyncMock(return_value=True))
    uow.wallets = SimpleNamespace(
        get_by_id_for_update=AsyncMock(side_effect=read('wallet', wallet)), save=AsyncMock(),
    )
    uow.wallet_balances = SimpleNamespace(
        get_by_wallet_id_for_update=AsyncMock(side_effect=read('balance', balance)), save=AsyncMock(),
    )
    uow.ledger_accounts = SimpleNamespace(
        get_by_wallet_id_for_update=AsyncMock(side_effect=read('account', account)),
        get_sandbox_funding_for_update=AsyncMock(side_effect=read('funding', funding)), save=AsyncMock(),
    )
    uow.sandbox_top_ups = SimpleNamespace(add=AsyncMock())
    uow.ledger_transactions = SimpleNamespace(add=AsyncMock())
    uow.idempotency = SimpleNamespace(claim=AsyncMock(return_value=None), complete=AsyncMock())
    clock = SimpleNamespace(now=Mock(side_effect=read('clock', now)))
    command = CreateSandboxTopUpCommand(
        user_id=user.id, wallet_id=wallet.id, amount_minor=10000,
        currency=CurrencyEnum.USD, idempotency_key='top-up-request-1',
    )
    return SimpleNamespace(
        uow=uow, user=user, wallet=wallet, balance=balance, account=account, funding=funding,
        events=events, clock=clock, command=command,
        use_case=CreateSandboxTopUpUseCase(uow=uow, clock=clock, sandbox_enabled=True),
    )


def assert_no_financial_writes(ctx):
    ctx.uow.sandbox_top_ups.add.assert_not_awaited()
    ctx.uow.ledger_transactions.add.assert_not_awaited()
    ctx.uow.wallet_balances.save.assert_not_awaited()
    ctx.uow.idempotency.complete.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


async def test_operator_credits_another_users_wallet_with_one_balanced_journal(ctx, now):
    before = vars(ctx.balance).copy()
    result = await ctx.use_case.execute(cmd=ctx.command)
    top_up = ctx.uow.sandbox_top_ups.add.await_args.args[0]
    journal = ctx.uow.ledger_transactions.add.await_args.args[0]
    saved = ctx.uow.wallet_balances.save.await_args.args[0]
    assert ctx.wallet.user_id != ctx.user.id
    assert result.top_up_id == top_up.id == journal.sandbox_top_up_id
    assert journal.transfer_id is None
    assert top_up.wallet_id == ctx.wallet.id
    assert top_up.initiated_by_user_id == ctx.user.id
    assert top_up.status is SandboxTopUpStatusEnum.COMPLETED
    assert top_up.created_at == top_up.completed_at == top_up.updated_at == journal.posted_at == now
    assert saved.wallet_id == ctx.wallet.id
    assert saved.posted_minor == 12000
    assert saved.version == 1
    assert saved.updated_at == now
    assert vars(ctx.balance) == before
    assert len(journal.entries) == 2
    debit, credit = journal.entries
    assert debit.side is LedgerEntrySideEnum.DEBIT
    assert debit.ledger_account_id == ctx.funding.id
    assert credit.side is LedgerEntrySideEnum.CREDIT
    assert credit.ledger_account_id == ctx.account.id
    assert debit.amount_minor == credit.amount_minor == 10000
    assert debit.currency is credit.currency is ctx.wallet.currency
    assert debit.ledger_transaction_id == credit.ledger_transaction_id == journal.id
    ctx.uow.sandbox_top_ups.add.assert_awaited_once()
    ctx.uow.ledger_transactions.add.assert_awaited_once()
    ctx.uow.wallet_balances.save.assert_awaited_once()
    ctx.uow.commit.assert_awaited_once()
    ctx.uow.wallets.save.assert_not_awaited()
    ctx.uow.ledger_accounts.save.assert_not_awaited()


async def test_lock_order_then_one_time_read_after_locks(ctx):
    await ctx.use_case.execute(ctx.command)
    assert ctx.events == ['user', 'wallet', 'balance', 'account', 'funding', 'clock']
    ctx.uow.wallet_balances.get_by_wallet_id_for_update.assert_awaited_once_with(wallet_id=ctx.wallet.id)
    ctx.uow.ledger_accounts.get_sandbox_funding_for_update.assert_awaited_once_with(currency=ctx.command.currency)
    assert ctx.uow.sandbox_operator_reader.is_operator.await_args_list[0].args == (ctx.user.id,)
    assert ctx.uow.sandbox_operator_reader.is_operator.await_args_list[1].args == (ctx.user.id,)


@pytest.mark.parametrize('currency', list(CurrencyEnum))
async def test_supports_each_currency_with_matching_funding_account(ctx, now, currency):
    ctx.wallet.currency = currency
    account = LedgerAccount.for_wallet(wallet_id=ctx.wallet.id, currency=currency, now=now)
    funding = LedgerAccount.for_sandbox_funding(currency=currency, now=now)
    ctx.uow.ledger_accounts.get_by_wallet_id_for_update.side_effect = None
    ctx.uow.ledger_accounts.get_by_wallet_id_for_update.return_value = account
    ctx.uow.ledger_accounts.get_sandbox_funding_for_update.side_effect = None
    ctx.uow.ledger_accounts.get_sandbox_funding_for_update.return_value = funding
    await ctx.use_case.execute(replace(ctx.command, currency=currency))
    journal = ctx.uow.ledger_transactions.add.await_args.args[0]
    assert all(entry.currency is currency for entry in journal.entries)
    assert journal.entries[0].ledger_account_id == funding.id


@pytest.mark.parametrize('amount', [0, -1, True, False, 1.5, '100', None, MAX_SANDBOX_TOP_UP_AMOUNT_MINOR + 1])
async def test_invalid_amount_rejected_before_uow(ctx, amount):
    with pytest.raises(InvalidSandboxTopUpAmountError):
        await ctx.use_case.execute(replace(ctx.command, amount_minor=amount))
    ctx.uow.__aenter__.assert_not_awaited()
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('key', ['', ' ', 'has space', 'line\nbreak', '\t', 'ключ', 'x' * 256, None, 1])
async def test_invalid_idempotency_key_rejected_before_uow(ctx, key):
    with pytest.raises(InvalidIdempotencyKeyError):
        await ctx.use_case.execute(replace(ctx.command, idempotency_key=key))
    ctx.uow.__aenter__.assert_not_awaited()


@pytest.mark.parametrize(('field', 'value'), [('user_id', None), ('wallet_id', 'uuid'), ('currency', 'USD')])
async def test_invalid_identity_and_currency_types_rejected_before_uow(ctx, field, value):
    with pytest.raises(TypeError):
        await ctx.use_case.execute(replace(ctx.command, **{field: value}))
    ctx.uow.__aenter__.assert_not_awaited()


@pytest.mark.parametrize('stage', ['read', 'lock'])
@pytest.mark.parametrize('status', [None, UserStatusEnum.PENDING_CONFIRMATION, UserStatusEnum.SUSPENDED, UserStatusEnum.CLOSED])
async def test_missing_or_inactive_operator_cannot_top_up(ctx, stage, status):
    user = None if status is None else replace(ctx.user, status=status)
    method = ctx.uow.users.get_by_id if stage == 'read' else ctx.uow.users.get_by_id_for_update
    method.side_effect = None
    method.return_value = user
    with pytest.raises(UserNotFoundError if status is None else UserInactiveError):
        await ctx.use_case.execute(ctx.command)
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    if stage == 'read':
        ctx.uow.idempotency.claim.assert_not_awaited()
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('owns_wallet', [False, True])
async def test_wallet_ownership_does_not_grant_operator_permission(ctx, owns_wallet):
    if owns_wallet:
        ctx.wallet.user_id = ctx.user.id
    ctx.uow.sandbox_operator_reader.is_operator.return_value = False
    with pytest.raises(SandboxOperatorRequiredError):
        await ctx.use_case.execute(ctx.command)
    ctx.uow.idempotency.claim.assert_not_awaited()
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


async def test_operator_permission_is_rechecked_under_user_lock(ctx):
    ctx.uow.sandbox_operator_reader.is_operator.side_effect = [True, False]
    with pytest.raises(SandboxOperatorRequiredError):
        await ctx.use_case.execute(ctx.command)
    ctx.uow.users.get_by_id_for_update.assert_awaited_once_with(ctx.user.id)
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


async def test_sandbox_is_disabled_by_default(ctx):
    use_case = CreateSandboxTopUpUseCase(ctx.uow, ctx.clock)
    with pytest.raises(SandboxDisabledError):
        await use_case.execute(ctx.command)
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('value', [None, 0, 1, 'true'])
def test_enabled_setting_must_be_a_boolean(ctx, value):
    with pytest.raises(ValueError):
        CreateSandboxTopUpUseCase(ctx.uow, ctx.clock, sandbox_enabled=value)


@pytest.mark.parametrize('limit', [0, -1, True, 1.5, MAX_SANDBOX_TOP_UP_AMOUNT_MINOR + 1])
def test_configured_limit_must_be_a_positive_bigint(ctx, limit):
    with pytest.raises(ValueError):
        CreateSandboxTopUpUseCase(ctx.uow, ctx.clock, max_amount_minor=limit)


async def test_configured_limit_blocks_new_top_up(ctx):
    use_case = CreateSandboxTopUpUseCase(ctx.uow, ctx.clock, sandbox_enabled=True, max_amount_minor=9999)
    with pytest.raises(SandboxTopUpLimitExceededError):
        await use_case.execute(ctx.command)
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('change', ['missing', 'wrong_id'])
async def test_missing_or_wrong_wallet_is_rejected(ctx, change):
    ctx.uow.wallets.get_by_id_for_update.side_effect = None
    ctx.uow.wallets.get_by_id_for_update.return_value = None if change == 'missing' else replace(ctx.wallet, id=uuid4())
    with pytest.raises(WalletNotFoundError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('status', [WalletStatusEnum.FROZEN, WalletStatusEnum.CLOSED])
async def test_target_wallet_must_be_active(ctx, status):
    ctx.wallet.status = status
    with pytest.raises(WalletNotActiveError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


async def test_target_wallet_currency_must_match_command(ctx):
    with pytest.raises(SandboxTopUpCurrencyMismatchError):
        await ctx.use_case.execute(replace(ctx.command, currency=CurrencyEnum.EUR))
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('change', ['missing_balance', 'wrong_balance', 'missing_account', 'wrong_account', 'currency', 'type'])
async def test_missing_or_inconsistent_wallet_accounting_state_is_rejected(ctx, now, change):
    if change in ('missing_balance', 'wrong_balance'):
        method = ctx.uow.wallet_balances.get_by_wallet_id_for_update
        value = None if change == 'missing_balance' else replace(ctx.balance, wallet_id=uuid4())
    else:
        method = ctx.uow.ledger_accounts.get_by_wallet_id_for_update
        values = {
            'missing_account': None,
            'wrong_account': LedgerAccount.for_wallet(wallet_id=uuid4(), currency=ctx.wallet.currency, now=now),
            'currency': LedgerAccount.for_wallet(wallet_id=ctx.wallet.id, currency=CurrencyEnum.EUR, now=now),
            'type': SimpleNamespace(wallet_id=ctx.wallet.id, currency=ctx.wallet.currency, account_type=AccountType.ASSET),
        }
        value = values[change]
    method.side_effect = None
    method.return_value = value
    with pytest.raises(WalletAccountingStateError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('change', ['missing', 'wallet', 'currency', 'type', 'code', 'same_id'])
async def test_funding_must_be_the_preprovisioned_system_asset_account(ctx, now, change):
    values = {
        'missing': None,
        'wallet': ctx.account,
        'currency': LedgerAccount.for_sandbox_funding(currency=CurrencyEnum.EUR, now=now),
        'type': SimpleNamespace(**{**vars(ctx.funding), 'account_type': AccountType.LIABILITY}),
        'code': SimpleNamespace(**{**vars(ctx.funding), 'code': LedgerAccountCode('SYS:OTHER:USD')}),
        'same_id': replace(ctx.funding, id=ctx.account.id),
    }
    ctx.uow.ledger_accounts.get_sandbox_funding_for_update.side_effect = None
    ctx.uow.ledger_accounts.get_sandbox_funding_for_update.return_value = values[change]
    with pytest.raises(SandboxFundingAccountError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('which', ['account', 'funding'])
async def test_closed_wallet_or_funding_account_is_rejected(ctx, which):
    getattr(ctx, which).close()
    with pytest.raises(LedgerAccountClosedError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('change', ['balance', 'version'])
async def test_overflow_preserves_repository_balance(ctx, change):
    if change == 'balance':
        ctx.balance.posted_minor = MAX_BALANCE_MINOR
    else:
        ctx.balance.version = MAX_BALANCE_MINOR
    before = vars(ctx.balance).copy()
    with pytest.raises(WalletBalanceOverflowError):
        await ctx.use_case.execute(ctx.command)
    assert vars(ctx.balance) == before
    assert_no_financial_writes(ctx)


async def test_exact_balance_limit_is_allowed(ctx):
    ctx.balance.posted_minor = MAX_BALANCE_MINOR - ctx.command.amount_minor
    await ctx.use_case.execute(ctx.command)
    saved = ctx.uow.wallet_balances.save.await_args.args[0]
    assert saved.posted_minor == MAX_BALANCE_MINOR


async def test_journal_failure_leaves_repository_balance_unchanged(ctx, monkeypatch):
    before = vars(ctx.balance).copy()
    monkeypatch.setattr(top_up_module.LedgerTransaction, 'for_sandbox_top_up', Mock(side_effect=RuntimeError('journal failed')))
    with pytest.raises(RuntimeError, match='journal failed'):
        await ctx.use_case.execute(ctx.command)
    assert vars(ctx.balance) == before
    assert_no_financial_writes(ctx)
    assert ctx.uow.__aexit__.await_args.args[0] is RuntimeError


@pytest.mark.parametrize('stage', ['top_up', 'journal', 'balance', 'replay', 'commit'])
async def test_storage_failure_exits_uow_with_error_without_success(ctx, stage):
    error = RuntimeError('storage unavailable')
    method = {
        'top_up': ctx.uow.sandbox_top_ups.add, 'journal': ctx.uow.ledger_transactions.add,
        'balance': ctx.uow.wallet_balances.save, 'replay': ctx.uow.idempotency.complete, 'commit': ctx.uow.commit,
    }[stage]
    method.side_effect = error
    with pytest.raises(RuntimeError, match='storage unavailable'):
        await ctx.use_case.execute(ctx.command)
    assert ctx.uow.__aexit__.await_args.args[1] is error
    if stage != 'commit':
        ctx.uow.commit.assert_not_awaited()


async def test_all_records_and_replay_are_saved_before_single_commit(ctx):
    order = []
    for label, method in (
        ('top_up', ctx.uow.sandbox_top_ups.add), ('journal', ctx.uow.ledger_transactions.add),
        ('balance', ctx.uow.wallet_balances.save), ('replay', ctx.uow.idempotency.complete), ('commit', ctx.uow.commit),
    ):
        method.side_effect = lambda *args, label=label, **kwargs: order.append(label)
    await ctx.use_case.execute(ctx.command)
    assert order == ['top_up', 'journal', 'balance', 'replay', 'commit']


async def test_retry_returns_same_id_without_repeating_posting(ctx):
    first = await ctx.use_case.execute(ctx.command)
    claimed = ctx.uow.idempotency.claim.await_args.kwargs
    completed = ctx.uow.idempotency.complete.await_args.kwargs
    assert claimed == {
        'user_id': ctx.user.id, 'scope': SANDBOX_TOP_UP_IDEMPOTENCY_SCOPE,
        'key': ctx.command.idempotency_key, 'payload_hash': completed['payload_hash'],
    }
    assert claimed['scope'] != TRANSFER_IDEMPOTENCY_SCOPE
    assert completed['resource_id'] == first.top_up_id
    assert len(claimed['payload_hash']) == 64
    ctx.uow.idempotency.claim.return_value = IdempotencyRecord(
        payload_hash=claimed['payload_hash'], resource_id=first.top_up_id,
    )
    second = await ctx.use_case.execute(ctx.command)
    assert first == second
    ctx.uow.wallets.get_by_id_for_update.assert_awaited_once()
    ctx.uow.sandbox_top_ups.add.assert_awaited_once()
    ctx.uow.ledger_transactions.add.assert_awaited_once()
    ctx.uow.commit.assert_awaited_once()


@pytest.mark.parametrize('field', ['wallet_id', 'amount_minor', 'currency'])
async def test_same_key_with_different_payload_conflicts(ctx, field):
    ctx.uow.idempotency.claim.return_value = IdempotencyRecord(
        payload_hash=CreateSandboxTopUpUseCase._payload_hash(ctx.command), resource_id=uuid4(),
    )
    values = {'wallet_id': uuid4(), 'amount_minor': 20000, 'currency': CurrencyEnum.EUR}
    with pytest.raises(IdempotencyConflictError):
        await ctx.use_case.execute(replace(ctx.command, **{field: values[field]}))
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


async def test_unfinished_replay_cannot_create_second_top_up(ctx):
    ctx.uow.idempotency.claim.return_value = IdempotencyRecord(
        payload_hash=CreateSandboxTopUpUseCase._payload_hash(ctx.command), resource_id=None,
    )
    with pytest.raises(IdempotencyInProgressError):
        await ctx.use_case.execute(ctx.command)
    assert_no_financial_writes(ctx)


async def test_claim_timeout_propagates_before_user_lock(ctx):
    ctx.uow.idempotency.claim.side_effect = IdempotencyInProgressError()
    with pytest.raises(IdempotencyInProgressError):
        await ctx.use_case.execute(ctx.command)
    ctx.uow.users.get_by_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


@pytest.mark.parametrize('change', ['disabled', 'lower_limit'])
async def test_authorized_replay_survives_disabled_sandbox_or_lowered_limit(ctx, change):
    top_up_id = uuid4()
    ctx.uow.idempotency.claim.return_value = IdempotencyRecord(
        payload_hash=CreateSandboxTopUpUseCase._payload_hash(ctx.command), resource_id=top_up_id,
    )
    use_case = CreateSandboxTopUpUseCase(
        ctx.uow, ctx.clock, sandbox_enabled=change != 'disabled',
        max_amount_minor=1 if change == 'lower_limit' else MAX_SANDBOX_TOP_UP_AMOUNT_MINOR,
    )
    result = await use_case.execute(ctx.command)
    assert result.top_up_id == top_up_id
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    assert_no_financial_writes(ctx)


async def test_revoked_operator_cannot_read_a_cached_result(ctx):
    ctx.uow.idempotency.claim.return_value = IdempotencyRecord(
        payload_hash=CreateSandboxTopUpUseCase._payload_hash(ctx.command), resource_id=uuid4(),
    )
    ctx.uow.sandbox_operator_reader.is_operator.return_value = False
    with pytest.raises(SandboxOperatorRequiredError):
        await ctx.use_case.execute(ctx.command)
    ctx.uow.idempotency.claim.assert_not_awaited()
    assert_no_financial_writes(ctx)


async def test_new_key_is_a_new_top_up_intent(ctx):
    first = await ctx.use_case.execute(ctx.command)
    second = await ctx.use_case.execute(replace(ctx.command, idempotency_key='top-up-request-2'))
    assert first.top_up_id != second.top_up_id
    assert ctx.uow.commit.await_count == 2

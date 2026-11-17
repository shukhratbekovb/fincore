from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.application.auth.errors import UserInactiveError
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.create_wallet import CreateWalletCommand
from backend.application.wallet.errors import WalletNumberAlreadyExistsError
from backend.application.wallet.use_cases.create_wallet import CreateWalletUseCase
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, Username
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.value_objects import WalletName, WalletNumber


@pytest.fixture
def context(now):
    user = User.register(Username('alice'), Email('alice@example.com'))
    user.activate()
    uow = AsyncMock()
    uow.users = SimpleNamespace(get_by_id_for_update=AsyncMock(return_value=user))
    uow.wallets = SimpleNamespace(add=AsyncMock())
    uow.wallet_balances = SimpleNamespace(add=AsyncMock())
    uow.ledger_accounts = SimpleNamespace(add=AsyncMock())
    generator = Mock()
    generator.generate.return_value = WalletNumber('12345678901234567890')
    clock = SimpleNamespace(now=lambda: now)
    command = CreateWalletCommand(user_id=user.id, name=WalletName('Main'))
    return SimpleNamespace(user=user, uow=uow, generator=generator, command=command,
                           clock=clock, use_case=CreateWalletUseCase(uow=uow, number_generator=generator, clock=clock))


@pytest.mark.parametrize('currency', list(CurrencyEnum))
async def test_creates_wallet_for_locked_owner(context, currency):
    ctx = context
    command = CreateWalletCommand(user_id=ctx.user.id, name=WalletName('Main'), currency=currency)
    result = await ctx.use_case.execute(command)
    wallet = ctx.uow.wallets.add.call_args.args[0]
    ctx.uow.users.get_by_id_for_update.assert_awaited_once_with(ctx.user.id)
    assert wallet.user_id == ctx.user.id
    assert wallet.name == command.name
    assert wallet.number == ctx.generator.generate.return_value
    assert wallet.currency == currency
    assert wallet.status == WalletStatusEnum.ACTIVE
    assert result.wallet_id == wallet.id
    ctx.uow.commit.assert_awaited_once()


def test_default_currency_is_unchanged(context):
    assert context.command.currency == CurrencyEnum.USD


async def test_missing_user_does_not_create_wallet(context):
    ctx = context
    ctx.uow.users.get_by_id_for_update.return_value = None
    with pytest.raises(UserNotFoundError):
        await ctx.use_case.execute(ctx.command)
    ctx.generator.generate.assert_not_called()
    ctx.uow.wallets.add.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('status', [UserStatusEnum.PENDING_CONFIRMATION, UserStatusEnum.SUSPENDED, UserStatusEnum.CLOSED])
async def test_current_inactive_status_prevents_creation(context, status):
    ctx = context
    # The status loaded under lock takes precedence over an earlier authenticated state.
    ctx.user.status = status
    with pytest.raises(UserInactiveError):
        await ctx.use_case.execute(ctx.command)
    ctx.generator.generate.assert_not_called()
    ctx.uow.wallets.add.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('stage', ['generate', 'add', 'balance', 'account', 'commit'])
async def test_storage_or_generation_failure_propagates(context, stage):
    ctx = context
    operation = {'generate': ctx.generator.generate, 'add': ctx.uow.wallets.add,
                 'balance': ctx.uow.wallet_balances.add, 'account': ctx.uow.ledger_accounts.add,
                 'commit': ctx.uow.commit}[stage]
    operation.side_effect = RuntimeError('unavailable')
    with pytest.raises(RuntimeError, match='unavailable'):
        await ctx.use_case.execute(ctx.command)
    assert ctx.uow.__aexit__.call_args.args[0] is RuntimeError
    if stage != 'commit':
        ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('stage', ['add', 'commit'])
async def test_number_collision_does_not_report_success(context, stage):
    ctx = context
    operation = ctx.uow.wallets.add if stage == 'add' else ctx.uow.commit
    operation.side_effect = WalletNumberAlreadyExistsError()
    with pytest.raises(WalletNumberAlreadyExistsError):
        await ctx.use_case.execute(ctx.command)
    if stage == 'add':
        ctx.uow.commit.assert_not_awaited()


async def test_allows_multiple_wallets_for_same_owner_and_currency(context):
    ctx = context
    ctx.generator.generate.side_effect = [WalletNumber('0' * 19 + '1'), WalletNumber('0' * 19 + '2')]
    first = await ctx.use_case.execute(ctx.command)
    second = await ctx.use_case.execute(ctx.command)
    assert first.wallet_id != second.wallet_id
    assert ctx.uow.wallets.add.await_count == 2


@pytest.mark.parametrize('stage', ['add', 'commit'])
async def test_collision_retries_after_transaction_exit_with_new_number(context, stage):
    ctx = context
    events = []
    ctx.uow.__aenter__.side_effect = lambda: events.append('enter')
    ctx.uow.__aexit__.side_effect = lambda *args: events.append(('exit', args[0]))
    numbers = [WalletNumber('0' * 19 + '1'), WalletNumber('0' * 19 + '2')]
    ctx.generator.generate.side_effect = numbers
    operation = ctx.uow.wallets.add if stage == 'add' else ctx.uow.commit
    operation.side_effect = [WalletNumberAlreadyExistsError(), None]

    result = await ctx.use_case.execute(ctx.command)

    saved = [call.args[0] for call in ctx.uow.wallets.add.await_args_list]
    assert [wallet.number for wallet in saved] == numbers
    assert result.wallet_id == saved[-1].id
    assert events == ['enter', ('exit', WalletNumberAlreadyExistsError), 'enter', ('exit', None)]
    assert ctx.uow.users.get_by_id_for_update.await_count == 2


async def test_collision_retry_limit_is_enforced(context):
    ctx = context
    ctx.uow.commit.side_effect = WalletNumberAlreadyExistsError()
    with pytest.raises(WalletNumberAlreadyExistsError):
        await ctx.use_case.execute(ctx.command)
    assert ctx.generator.generate.call_count == 3
    assert ctx.uow.__aenter__.await_count == 3
    assert ctx.uow.__aexit__.await_count == 3


async def test_one_attempt_disables_retry(context):
    ctx = context
    use_case = CreateWalletUseCase(ctx.uow, ctx.generator, clock=ctx.clock, max_number_attempts=1)
    ctx.uow.wallets.add.side_effect = WalletNumberAlreadyExistsError()
    with pytest.raises(WalletNumberAlreadyExistsError):
        await use_case.execute(ctx.command)
    assert ctx.generator.generate.call_count == 1


@pytest.mark.parametrize('attempts', [0, -1])
def test_retry_limit_must_be_positive(context, attempts):
    with pytest.raises(ValueError):
        CreateWalletUseCase(context.uow, context.generator, clock=context.clock, max_number_attempts=attempts)


async def test_retry_rechecks_user_status(context):
    ctx = context
    inactive = User.register(Username('alice'), Email('alice@example.com'))
    ctx.uow.users.get_by_id_for_update.side_effect = [ctx.user, inactive]
    ctx.uow.wallets.add.side_effect = WalletNumberAlreadyExistsError()
    with pytest.raises(UserInactiveError):
        await ctx.use_case.execute(ctx.command)
    assert ctx.generator.generate.call_count == 1
    ctx.uow.commit.assert_not_awaited()


async def test_create_wallet_accepts_real_generator(context):
    from backend.infrastructure.wallet.number_generator import RandomWalletNumberGenerator

    ctx = context
    use_case = CreateWalletUseCase(ctx.uow, RandomWalletNumberGenerator(), clock=ctx.clock)
    result = await use_case.execute(ctx.command)
    wallet = ctx.uow.wallets.add.call_args.args[0]
    assert result.wallet_id == wallet.id
    assert len(wallet.number.value) == 20


async def test_wallet_balance_and_account_are_saved_before_one_commit(context, now):
    from backend.domain.ledger_account.enums import AccountType

    ctx = context
    order = []
    for label, method in [('wallet', ctx.uow.wallets.add),
                          ('balance', ctx.uow.wallet_balances.add),
                          ('account', ctx.uow.ledger_accounts.add),
                          ('commit', ctx.uow.commit)]:
        method.side_effect = lambda *args, label=label: order.append(label)
    result = await ctx.use_case.execute(ctx.command)
    wallet = ctx.uow.wallets.add.call_args.args[0]
    balance = ctx.uow.wallet_balances.add.call_args.args[0]
    account = ctx.uow.ledger_accounts.add.call_args.args[0]
    assert order == ['wallet', 'balance', 'account', 'commit']
    assert result.wallet_id == wallet.id == balance.wallet_id == account.wallet_id
    assert balance.posted_minor == balance.version == 0
    assert balance.created_at == account.created_at == now
    assert account.currency == wallet.currency == ctx.command.currency
    assert account.account_type == AccountType.LIABILITY
    assert account.code.value == f'WALLET:{wallet.id}:{wallet.currency.value}'
    ctx.uow.commit.assert_awaited_once()


async def test_commit_collision_recreates_all_three_records(context):
    ctx = context
    ctx.uow.commit.side_effect = [WalletNumberAlreadyExistsError(), None]
    ctx.generator.generate.side_effect = [WalletNumber('1' * 20), WalletNumber('2' * 20)]
    result = await ctx.use_case.execute(ctx.command)
    wallets = [call.args[0] for call in ctx.uow.wallets.add.await_args_list]
    balances = [call.args[0] for call in ctx.uow.wallet_balances.add.await_args_list]
    accounts = [call.args[0] for call in ctx.uow.ledger_accounts.add.await_args_list]
    assert len(wallets) == len(balances) == len(accounts) == 2
    assert wallets[0].id != wallets[1].id
    for wallet, balance, account in zip(wallets, balances, accounts):
        assert wallet.id == balance.wallet_id == account.wallet_id
    assert result.wallet_id == wallets[1].id

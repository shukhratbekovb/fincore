from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.application.wallet.dtos.close_wallet import CloseWalletCommand
from backend.application.wallet.dtos.rename_wallet import RenameWalletCommand
from backend.application.wallet.errors import WalletAccountingStateError, WalletBalanceNotZeroError, WalletNotFoundError
from backend.application.wallet.use_cases.close_wallet import CloseWalletUseCase
from backend.application.wallet.use_cases.rename_wallet import RenameWalletUseCase
from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_account.enums import AccountStatus
from backend.domain.share.enums import CurrencyEnum
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.errors import WalletClosedError
from backend.domain.wallet.value_objects import WalletName, WalletNumber
from backend.domain.wallet_balance.entities import WalletBalance


@pytest.fixture
def ctx(now):
    wallet = Wallet.create(user_id=uuid4(), name=WalletName('Main'),
                           number=WalletNumber('1' * 20), currency=CurrencyEnum.USD)
    balance = WalletBalance.create(wallet_id=wallet.id, now=now)
    account = LedgerAccount.for_wallet(wallet_id=wallet.id, currency=wallet.currency, now=now)
    uow = AsyncMock()
    uow.wallets = SimpleNamespace(get_by_id_for_update=AsyncMock(return_value=wallet), save=AsyncMock())
    uow.wallet_balances = SimpleNamespace(get_by_wallet_id_for_update=AsyncMock(return_value=balance))
    uow.ledger_accounts = SimpleNamespace(get_by_wallet_id_for_update=AsyncMock(return_value=account), save=AsyncMock())
    return SimpleNamespace(wallet=wallet, balance=balance, account=account, uow=uow,
                           close=CloseWalletUseCase(uow), rename=RenameWalletUseCase(uow))


@pytest.mark.parametrize('frozen', [False, True])
async def test_rename_open_wallet(ctx, frozen):
    if frozen:
        ctx.wallet.freeze()
    name = WalletName('Savings')
    await ctx.rename.execute(RenameWalletCommand(ctx.wallet.user_id, ctx.wallet.id, name))
    assert ctx.wallet.name == name
    ctx.uow.wallets.save.assert_awaited_once_with(ctx.wallet)
    ctx.uow.commit.assert_awaited_once()


async def test_rename_closed_wallet_rejected(ctx):
    ctx.wallet.close()
    with pytest.raises(WalletClosedError):
        await ctx.rename.execute(RenameWalletCommand(ctx.wallet.user_id, ctx.wallet.id, WalletName('Other')))
    assert ctx.wallet.name.value == 'Main'
    ctx.uow.wallets.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('operation', ['close', 'rename'])
@pytest.mark.parametrize('missing', [True, False])
async def test_missing_or_foreign_wallet_not_found(ctx, operation, missing):
    actor = ctx.wallet.user_id if missing else uuid4()
    if missing:
        ctx.uow.wallets.get_by_id_for_update.return_value = None
    command = CloseWalletCommand(actor, ctx.wallet.id) if operation == 'close' else RenameWalletCommand(actor, ctx.wallet.id, WalletName('Other'))
    with pytest.raises(WalletNotFoundError):
        await getattr(ctx, operation).execute(command)
    ctx.uow.wallets.save.assert_not_awaited()
    ctx.uow.wallet_balances.get_by_wallet_id_for_update.assert_not_awaited()
    ctx.uow.ledger_accounts.get_by_wallet_id_for_update.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('initial_status', ['active', 'frozen', 'closed'])
async def test_close_updates_both_statuses_and_preserves_balance_and_history(ctx, initial_status):
    if initial_status == 'frozen':
        ctx.wallet.freeze()
    elif initial_status == 'closed':
        ctx.wallet.close()
        ctx.account.close()
    before = vars(ctx.balance).copy()
    await ctx.close.execute(CloseWalletCommand(ctx.wallet.user_id, ctx.wallet.id))
    assert ctx.wallet.status == WalletStatusEnum.CLOSED
    assert ctx.account.status == AccountStatus.CLOSED
    assert vars(ctx.balance) == before
    ctx.uow.wallets.save.assert_awaited_once_with(ctx.wallet)
    ctx.uow.ledger_accounts.save.assert_awaited_once_with(ctx.account)
    ctx.uow.commit.assert_awaited_once()


async def test_close_rejects_nonzero_balance(ctx, now):
    ctx.balance.credit(1, now=now)
    with pytest.raises(WalletBalanceNotZeroError):
        await ctx.close.execute(CloseWalletCommand(ctx.wallet.user_id, ctx.wallet.id))
    assert ctx.wallet.status == WalletStatusEnum.ACTIVE
    assert ctx.account.status == AccountStatus.ACTIVE
    ctx.uow.wallets.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('corruption', ['missing_balance', 'wrong_balance', 'missing_account', 'wrong_account', 'wrong_currency', 'system_account'])
async def test_close_rejects_missing_or_inconsistent_accounting_state(ctx, now, corruption):
    if corruption == 'missing_balance':
        ctx.uow.wallet_balances.get_by_wallet_id_for_update.return_value = None
    elif corruption == 'wrong_balance':
        ctx.balance.wallet_id = uuid4()
    elif corruption == 'missing_account':
        ctx.uow.ledger_accounts.get_by_wallet_id_for_update.return_value = None
    elif corruption == 'wrong_account':
        ctx.uow.ledger_accounts.get_by_wallet_id_for_update.return_value = LedgerAccount.for_wallet(wallet_id=uuid4(), currency=ctx.wallet.currency, now=now)
    elif corruption == 'wrong_currency':
        ctx.uow.ledger_accounts.get_by_wallet_id_for_update.return_value = LedgerAccount.for_wallet(wallet_id=ctx.wallet.id, currency=CurrencyEnum.EUR, now=now)
    else:
        # Malformed adapter result must not allow a non-liability account.
        ctx.uow.ledger_accounts.get_by_wallet_id_for_update.return_value = SimpleNamespace(wallet_id=ctx.wallet.id, currency=ctx.wallet.currency, account_type='asset')
    with pytest.raises(WalletAccountingStateError):
        await ctx.close.execute(CloseWalletCommand(ctx.wallet.user_id, ctx.wallet.id))
    assert ctx.wallet.status == WalletStatusEnum.ACTIVE
    ctx.uow.wallets.save.assert_not_awaited()
    ctx.uow.ledger_accounts.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


async def test_close_lock_order_then_one_commit(ctx):
    order = []
    for label, method, result in [
        ('wallet', ctx.uow.wallets.get_by_id_for_update, ctx.wallet),
        ('balance', ctx.uow.wallet_balances.get_by_wallet_id_for_update, ctx.balance),
        ('account', ctx.uow.ledger_accounts.get_by_wallet_id_for_update, ctx.account),
        ('save_wallet', ctx.uow.wallets.save, None),
        ('save_account', ctx.uow.ledger_accounts.save, None),
        ('commit', ctx.uow.commit, None),
    ]:
        def record(*args, label=label, result=result):
            order.append(label)
            return result
        method.side_effect = record
    await ctx.close.execute(CloseWalletCommand(ctx.wallet.user_id, ctx.wallet.id))
    assert order == ['wallet', 'balance', 'account', 'save_wallet', 'save_account', 'commit']


@pytest.mark.parametrize(('operation', 'stage'), [('close', 'wallet'), ('close', 'account'), ('close', 'commit'), ('rename', 'wallet'), ('rename', 'commit')])
async def test_storage_failure_propagates_without_success(ctx, operation, stage):
    method = {'wallet': ctx.uow.wallets.save, 'account': ctx.uow.ledger_accounts.save, 'commit': ctx.uow.commit}[stage]
    method.side_effect = RuntimeError('storage failure')
    command = CloseWalletCommand(ctx.wallet.user_id, ctx.wallet.id) if operation == 'close' else RenameWalletCommand(ctx.wallet.user_id, ctx.wallet.id, WalletName('Other'))
    with pytest.raises(RuntimeError, match='storage failure'):
        await getattr(ctx, operation).execute(command)
    assert ctx.uow.__aexit__.call_args.args[0] is RuntimeError
    if stage != 'commit':
        ctx.uow.commit.assert_not_awaited()

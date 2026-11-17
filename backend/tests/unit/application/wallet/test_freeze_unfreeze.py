from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.application.auth.errors import UserInactiveError
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.freeze_wallet import FreezeWalletCommand
from backend.application.wallet.dtos.unfreeze_wallet import UnfreezeWalletCommand
from backend.application.wallet.errors import WalletAccountingStateError, WalletNotFoundError
from backend.application.wallet.use_cases.freeze_wallet import FreezeWalletUseCase
from backend.application.wallet.use_cases.unfreeze_wallet import UnfreezeWalletUseCase
from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_account.enums import AccountStatus, AccountType
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, HashedPassword, Username
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.errors import WalletClosedError
from backend.domain.wallet.value_objects import WalletName, WalletNumber
from backend.domain.wallet_balance.entities import WalletBalance


@pytest.fixture(params=['freeze', 'unfreeze'])
def ctx(request, now):
    user = User.created_by_admin(Username('alice'), Email('alice@example.com'), HashedPassword('test-hash'))
    wallet = Wallet.create(user.id, WalletName('Main'), WalletNumber('1' * 20), CurrencyEnum.USD)
    if request.param == 'unfreeze':
        wallet.freeze()
    balance = WalletBalance.create(wallet_id=wallet.id, now=now)
    balance.credit(12345, now=now)
    account = LedgerAccount.for_wallet(wallet_id=wallet.id, currency=wallet.currency, now=now)
    uow = AsyncMock()
    uow.users.get_by_id_for_update.return_value = user
    uow.wallets.get_by_id_for_update.return_value = wallet
    uow.wallet_balances.get_by_wallet_id_for_update.return_value = balance
    uow.ledger_accounts.get_by_wallet_id_for_update.return_value = account
    uc, cmd, target = ((FreezeWalletUseCase(uow), FreezeWalletCommand(user.id, wallet.id), WalletStatusEnum.FROZEN)
                       if request.param == 'freeze' else
                       (UnfreezeWalletUseCase(uow), UnfreezeWalletCommand(user.id, wallet.id), WalletStatusEnum.ACTIVE))
    return SimpleNamespace(user=user, wallet=wallet, balance=balance, account=account, uow=uow,
                           uc=uc, cmd=cmd, target=target)


async def test_changes_only_wallet_status_once_and_preserves_money(ctx):
    balance_before, account_before = vars(ctx.balance).copy(), vars(ctx.account).copy()
    await ctx.uc.execute(ctx.cmd)
    assert ctx.wallet.status == ctx.target
    assert vars(ctx.balance) == balance_before and vars(ctx.account) == account_before
    assert ctx.account.status == AccountStatus.ACTIVE
    ctx.uow.wallets.save.assert_awaited_once_with(ctx.wallet)
    ctx.uow.commit.assert_awaited_once()
    ctx.uow.wallet_balances.save.assert_not_awaited()
    ctx.uow.ledger_accounts.save.assert_not_awaited()
    ctx.uow.ledger_transactions.add.assert_not_awaited()
    updated_at = ctx.wallet.updated_at
    await ctx.uc.execute(ctx.cmd)
    assert ctx.wallet.updated_at == updated_at
    ctx.uow.wallets.save.assert_awaited_once()
    ctx.uow.commit.assert_awaited_once()


@pytest.mark.parametrize('problem', ['missing', 'inactive'])
async def test_rechecks_user_inside_transaction_before_wallet_access(ctx, problem):
    if problem == 'missing':
        ctx.uow.users.get_by_id_for_update.return_value = None
    else:
        ctx.user.suspend()
    with pytest.raises(UserNotFoundError if problem == 'missing' else UserInactiveError):
        await ctx.uc.execute(ctx.cmd)
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('problem', ['missing', 'foreign'])
async def test_missing_and_foreign_wallet_have_same_error_before_accounting_access(ctx, problem):
    if problem == 'missing':
        ctx.uow.wallets.get_by_id_for_update.return_value = None
    else:
        ctx.wallet.user_id = uuid4()
    with pytest.raises(WalletNotFoundError):
        await ctx.uc.execute(ctx.cmd)
    ctx.uow.wallet_balances.get_by_wallet_id_for_update.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


async def test_closed_wallet_is_never_reopened(ctx):
    ctx.wallet.close()
    ctx.account.close()
    with pytest.raises(WalletClosedError):
        await ctx.uc.execute(ctx.cmd)
    assert ctx.wallet.status == WalletStatusEnum.CLOSED
    ctx.uow.wallets.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('corruption', ['missing_balance', 'wrong_balance', 'missing_account',
                                       'wrong_account', 'wrong_currency', 'wrong_type', 'closed_account'])
async def test_accounting_corruption_never_changes_wallet_status(ctx, corruption):
    before = ctx.wallet.status
    if corruption == 'missing_balance':
        ctx.uow.wallet_balances.get_by_wallet_id_for_update.return_value = None
    elif corruption == 'wrong_balance':
        ctx.balance.wallet_id = uuid4()
    elif corruption == 'missing_account':
        ctx.uow.ledger_accounts.get_by_wallet_id_for_update.return_value = None
    elif corruption == 'wrong_account':
        ctx.uow.ledger_accounts.get_by_wallet_id_for_update.return_value = SimpleNamespace(**{**vars(ctx.account), 'wallet_id': uuid4()})
    elif corruption == 'wrong_currency':
        ctx.uow.ledger_accounts.get_by_wallet_id_for_update.return_value = SimpleNamespace(**{**vars(ctx.account), 'currency': CurrencyEnum.EUR})
    elif corruption == 'wrong_type':
        ctx.uow.ledger_accounts.get_by_wallet_id_for_update.return_value = SimpleNamespace(**{**vars(ctx.account), 'account_type': AccountType.ASSET})
    else:
        ctx.account.close()
    with pytest.raises(WalletAccountingStateError):
        await ctx.uc.execute(ctx.cmd)
    assert ctx.wallet.status == before
    ctx.uow.wallets.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


async def test_accounting_is_checked_even_when_status_already_matches(ctx):
    ctx.wallet.status = ctx.target
    ctx.account.close()
    with pytest.raises(WalletAccountingStateError):
        await ctx.uc.execute(ctx.cmd)
    ctx.uow.commit.assert_not_awaited()


async def test_locks_actor_then_wallet_balance_account_before_write(ctx):
    order = []
    for name, method, result in [
        ('user', ctx.uow.users.get_by_id_for_update, ctx.user),
        ('wallet', ctx.uow.wallets.get_by_id_for_update, ctx.wallet),
        ('balance', ctx.uow.wallet_balances.get_by_wallet_id_for_update, ctx.balance),
        ('account', ctx.uow.ledger_accounts.get_by_wallet_id_for_update, ctx.account),
        ('save', ctx.uow.wallets.save, None), ('commit', ctx.uow.commit, None),
    ]:
        def record(*args, name=name, result=result):
            order.append(name)
            return result
        method.side_effect = record
    await ctx.uc.execute(ctx.cmd)
    assert order == ['user', 'wallet', 'balance', 'account', 'save', 'commit']


@pytest.mark.parametrize('stage', ['save', 'commit'])
async def test_storage_failure_is_not_reported_as_success(ctx, stage):
    method = ctx.uow.wallets.save if stage == 'save' else ctx.uow.commit
    method.side_effect = RuntimeError('storage unavailable')
    with pytest.raises(RuntimeError, match='storage unavailable'):
        await ctx.uc.execute(ctx.cmd)
    assert ctx.uow.__aexit__.call_args.args[0] is RuntimeError

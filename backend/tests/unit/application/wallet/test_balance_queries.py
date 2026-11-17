from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.application.auth.errors import UserInactiveError
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.get_my_balance_summary import GetMyBalanceSummaryCommand
from backend.application.wallet.dtos.get_wallet_balance import GetWalletBalanceCommand
from backend.application.wallet.errors import WalletAccountingStateError, WalletNotFoundError
from backend.application.wallet.queries.get_my_balance_summary import GetMyBalanceSummaryQuery
from backend.application.wallet.queries.get_wallet_balance import GetWalletBalanceQuery
from backend.application.wallet_balance.dtos.base import BalanceSummaryDTO, CurrencyBalanceDTO, WalletBalanceDTO
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, Username
from backend.domain.wallet_balance.entities import MAX_BALANCE_MINOR


@pytest.fixture
def ctx(now):
    user = User.register(Username('alice'), Email('alice@example.com'))
    user.activate()
    wallet_id = uuid4()
    balance = WalletBalanceDTO(
        wallet_id=wallet_id, currency=CurrencyEnum.USD, posted_minor=50000,
        available_minor=50000, spendable_minor=50000, version=7,
        updated_at=now - timedelta(minutes=5), as_of=now,
    )
    summary = BalanceSummaryDTO(totals=[
        CurrencyBalanceDTO(currency=CurrencyEnum.USD, posted_minor=50000, available_minor=50000, spendable_minor=40000),
        CurrencyBalanceDTO(currency=CurrencyEnum.UZS, posted_minor=900000, available_minor=900000, spendable_minor=900000),
    ], as_of=now)
    uow = AsyncMock()
    uow.users = SimpleNamespace(get_by_id=AsyncMock(return_value=user), get_by_id_for_update=AsyncMock())
    uow.wallet_balance_reader = SimpleNamespace(
        get_by_wallet_id_for_user=AsyncMock(return_value=balance), get_summary_for_user=AsyncMock(return_value=summary),
    )
    return SimpleNamespace(
        user=user, wallet_id=wallet_id, balance=balance, summary_result=summary, uow=uow,
        wallet=GetWalletBalanceQuery(uow), summary=GetMyBalanceSummaryQuery(uow),
        wallet_cmd=GetWalletBalanceCommand(user.id, wallet_id), summary_cmd=GetMyBalanceSummaryCommand(user.id),
    )


def reader(ctx, query):
    return (ctx.uow.wallet_balance_reader.get_by_wallet_id_for_user if query == 'wallet'
            else ctx.uow.wallet_balance_reader.get_summary_for_user)


def assert_read_only(ctx):
    ctx.uow.commit.assert_not_awaited()
    ctx.uow.users.get_by_id_for_update.assert_not_awaited()
    ctx.uow.wallet_balances.save.assert_not_awaited()
    ctx.uow.wallet_balances.get_by_wallet_id_for_update.assert_not_awaited()
    ctx.uow.ledger_accounts.get_by_wallet_id_for_update.assert_not_awaited()


async def test_wallet_balance_uses_owner_scoped_snapshot_projection(ctx, now):
    result = await ctx.wallet.execute(cmd=ctx.wallet_cmd)
    assert result is ctx.balance
    assert result.version == 7
    assert result.updated_at == now - timedelta(minutes=5)
    assert result.as_of == now
    reader(ctx, 'wallet').assert_awaited_once_with(ctx.wallet_id, user_id=ctx.user.id)
    assert_read_only(ctx)


async def test_summary_preserves_currency_separation_and_spendable_amount(ctx):
    result = await ctx.summary.execute(ctx.summary_cmd)
    assert result is ctx.summary_result
    assert [item.currency for item in result.totals] == [CurrencyEnum.USD, CurrencyEnum.UZS]
    usd = result.totals[0]
    assert usd.posted_minor == usd.available_minor == 50000
    assert usd.spendable_minor == 40000
    reader(ctx, 'summary').assert_awaited_once_with(user_id=ctx.user.id, currency=None)
    ctx.uow.wallet_reader.list_by_user_id.assert_not_awaited()
    assert_read_only(ctx)


@pytest.mark.parametrize('currency', list(CurrencyEnum))
async def test_summary_forwards_currency_to_reader_with_mandatory_actor(ctx, currency):
    await ctx.summary.execute(replace(ctx.summary_cmd, currency=currency))
    reader(ctx, 'summary').assert_awaited_once_with(user_id=ctx.user.id, currency=currency)


@pytest.mark.parametrize('query', ['wallet', 'summary'])
@pytest.mark.parametrize('status', [None, UserStatusEnum.PENDING_CONFIRMATION, UserStatusEnum.SUSPENDED, UserStatusEnum.CLOSED])
async def test_missing_or_inactive_user_cannot_read(ctx, query, status):
    ctx.uow.users.get_by_id.return_value = None if status is None else replace(ctx.user, status=status)
    with pytest.raises(UserNotFoundError if status is None else UserInactiveError):
        await getattr(ctx, query).execute(getattr(ctx, query + '_cmd'))
    reader(ctx, query).assert_not_awaited()
    assert_read_only(ctx)


@pytest.mark.parametrize('query', ['wallet', 'summary'])
async def test_invalid_user_id_rejected_before_uow(ctx, query):
    with pytest.raises(TypeError):
        await getattr(ctx, query).execute(replace(getattr(ctx, query + '_cmd'), user_id='uuid'))
    ctx.uow.__aenter__.assert_not_awaited()


async def test_invalid_wallet_id_rejected_before_uow(ctx):
    with pytest.raises(TypeError):
        await ctx.wallet.execute(replace(ctx.wallet_cmd, wallet_id=None))
    ctx.uow.__aenter__.assert_not_awaited()


async def test_invalid_summary_currency_rejected_before_uow(ctx):
    with pytest.raises(TypeError):
        await ctx.summary.execute(replace(ctx.summary_cmd, currency='USD'))
    ctx.uow.__aenter__.assert_not_awaited()


@pytest.mark.parametrize('change', ['missing_or_foreign', 'wrong_wallet'])
async def test_wallet_not_found_for_absent_foreign_or_wrong_projection(ctx, change):
    reader(ctx, 'wallet').return_value = None if change == 'missing_or_foreign' else replace(ctx.balance, wallet_id=uuid4())
    with pytest.raises(WalletNotFoundError):
        await ctx.wallet.execute(ctx.wallet_cmd)
    assert_read_only(ctx)


async def test_real_zero_balance_is_preserved(ctx):
    reader(ctx, 'wallet').return_value = replace(ctx.balance, posted_minor=0, available_minor=0, spendable_minor=0)
    result = await ctx.wallet.execute(ctx.wallet_cmd)
    assert result.posted_minor == result.available_minor == result.spendable_minor == 0
    assert result.wallet_id == ctx.wallet_id


async def test_no_matching_wallets_returns_empty_totals(ctx, now):
    reader(ctx, 'summary').return_value = BalanceSummaryDTO(totals=[], as_of=now)
    result = await ctx.summary.execute(ctx.summary_cmd)
    assert result.totals == []


async def test_summary_preserves_zero_currency_total(ctx, now):
    zero = CurrencyBalanceDTO(currency=CurrencyEnum.USD, posted_minor=0, available_minor=0, spendable_minor=0)
    reader(ctx, 'summary').return_value = BalanceSummaryDTO(totals=[zero], as_of=now)
    result = await ctx.summary.execute(ctx.summary_cmd)
    assert result.totals == [zero]


async def test_readable_frozen_balance_can_have_no_spendable_funds(ctx):
    reader(ctx, 'wallet').return_value = replace(ctx.balance, spendable_minor=0)
    result = await ctx.wallet.execute(ctx.wallet_cmd)
    assert result.posted_minor == 50000
    assert result.spendable_minor == 0


@pytest.mark.parametrize('query', ['wallet', 'summary'])
@pytest.mark.parametrize('error_type', [WalletAccountingStateError, RuntimeError])
async def test_corruption_or_reader_failure_propagates_without_zero_fallback(ctx, query, error_type):
    error = error_type('reader failed')
    reader(ctx, query).side_effect = error
    with pytest.raises(error_type):
        await getattr(ctx, query).execute(getattr(ctx, query + '_cmd'))
    assert ctx.uow.__aexit__.await_args.args[1] is error
    assert_read_only(ctx)


async def test_aggregate_can_exceed_single_wallet_bigint(ctx, now):
    amount = 2 * MAX_BALANCE_MINOR
    total = CurrencyBalanceDTO(currency=CurrencyEnum.USD, posted_minor=amount, available_minor=amount, spendable_minor=amount)
    reader(ctx, 'summary').return_value = BalanceSummaryDTO(totals=[total], as_of=now)
    result = await ctx.summary.execute(ctx.summary_cmd)
    assert result.totals[0].posted_minor == amount


@pytest.mark.parametrize('field', ['posted_minor', 'available_minor', 'spendable_minor'])
@pytest.mark.parametrize('value', [-1, True, 1.5, None])
def test_projection_amounts_must_be_nonnegative_integers(ctx, field, value):
    with pytest.raises(WalletAccountingStateError):
        replace(ctx.summary_result.totals[0], **{field: value})


@pytest.mark.parametrize('change', [{'available_minor': 50001}, {'spendable_minor': 50001}])
def test_projection_amount_ordering_is_checked(ctx, change):
    with pytest.raises(WalletAccountingStateError):
        replace(ctx.summary_result.totals[0], **change)


@pytest.mark.parametrize('change', [
    {'version': -1}, {'version': True}, {'version': MAX_BALANCE_MINOR + 1},
    {'posted_minor': MAX_BALANCE_MINOR + 1},
])
def test_single_wallet_balance_and_version_must_fit_bigint(ctx, change):
    with pytest.raises(WalletAccountingStateError):
        replace(ctx.balance, **change)


def test_projection_requires_currency_enum(ctx):
    with pytest.raises(TypeError):
        replace(ctx.balance, currency='USD')


def test_single_wallet_projection_requires_uuid(ctx):
    with pytest.raises(TypeError):
        replace(ctx.balance, wallet_id='uuid')


@pytest.mark.parametrize('field', ['updated_at', 'as_of'])
@pytest.mark.parametrize('invalid_type', [False, True])
def test_projection_times_must_be_aware(ctx, now, field, invalid_type):
    value = None if invalid_type else now.replace(tzinfo=None)
    with pytest.raises(WalletAccountingStateError):
        replace(ctx.balance, **{field: value})


def test_summary_time_must_be_aware(ctx, now):
    with pytest.raises(WalletAccountingStateError):
        replace(ctx.summary_result, as_of=now.replace(tzinfo=None))


@pytest.mark.parametrize('totals', [None, (), [None]])
def test_summary_requires_currency_projection_list(ctx, totals):
    with pytest.raises(WalletAccountingStateError):
        replace(ctx.summary_result, totals=totals)


def test_summary_cannot_repeat_a_currency(ctx):
    usd = ctx.summary_result.totals[0]
    with pytest.raises(WalletAccountingStateError):
        replace(ctx.summary_result, totals=[usd, usd])

from dataclasses import replace
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from backend.application.auth.errors import UserInactiveError
from backend.application.history.dtos.base import TransactionDTO, WalletTransactionDTO
from backend.application.history.dtos.filters import (
    MyTransactionsFilter, TransactionDirectionEnum, WalletTransactionFilter,
)
from backend.application.history.dtos.get_my_transactions import GetMyTransactionsCommand
from backend.application.history.errors import InvalidTransactionFilterError
from backend.application.history.pagination import history_cursor_context
from backend.application.history.queries.get_my_transactions import GetMyTransactionsQuery
from backend.application.share.dtos.pagination import CursorPosition
from backend.application.share.errors import InvalidCursorError, InvalidPaginationError
from backend.application.user.errors import UserNotFoundError
from backend.application.wallet.dtos.get_wallet_transactions import GetWalletTransactionsCommand
from backend.application.wallet.errors import WalletNotFoundError
from backend.application.wallet.queries.get_wallet_transactions import GetWalletTransactionsQuery
from backend.domain.ledger_transaction.enums import LedgerTransactionKindEnum
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, Username
from backend.infrastructure.pagination.cursor import HMACCursorCodec


@pytest.fixture
def ctx(now):
    user = User.register(Username('alice'), Email('alice@example.com'))
    user.activate()
    wallet_id = uuid4()
    item = TransactionDTO(
        id=UUID(int=100), source_type=LedgerTransactionKindEnum.P2P_TRANSFER,
        source_id=uuid4(), sender_wallet_id=wallet_id, receiver_wallet_id=uuid4(),
        amount_minor=10000, currency=CurrencyEnum.USD, direction=TransactionDirectionEnum.OUTGOING, posted_at=now,
    )
    wallet_item = WalletTransactionDTO(**vars(item), wallet_id=wallet_id)
    uow = AsyncMock()
    uow.users = SimpleNamespace(get_by_id=AsyncMock(return_value=user), get_by_id_for_update=AsyncMock())
    uow.transaction_history_reader = SimpleNamespace(
        list_by_user_id=AsyncMock(return_value=[item]),
        list_by_wallet_id_for_user=AsyncMock(return_value=[wallet_item]),
    )
    codec = HMACCursorCodec(b'history-query-tests-key-only-12345')
    return SimpleNamespace(
        user=user, wallet_id=wallet_id, item=item, wallet_item=wallet_item, uow=uow, codec=codec,
        personal=GetMyTransactionsQuery(uow, codec), wallet=GetWalletTransactionsQuery(uow, codec),
        personal_cmd=GetMyTransactionsCommand(user.id), wallet_cmd=GetWalletTransactionsCommand(user.id, wallet_id),
    )


def reader(ctx, query):
    return (ctx.uow.transaction_history_reader.list_by_user_id if query == 'personal'
            else ctx.uow.transaction_history_reader.list_by_wallet_id_for_user)


def cursor_context(command, query):
    return history_cursor_context(
        query='history.user' if query == 'personal' else 'history.wallet', user_id=command.user_id,
        wallet_id=command.filters.wallet_id if query == 'personal' else command.wallet_id, filters=command.filters,
    )


def assert_read_only(ctx):
    ctx.uow.commit.assert_not_awaited()
    ctx.uow.users.get_by_id_for_update.assert_not_awaited()
    ctx.uow.ledger_transactions.add.assert_not_awaited()
    ctx.uow.wallet_balances.save.assert_not_awaited()


@pytest.mark.parametrize('query', ['personal', 'wallet'])
async def test_returns_projected_page_with_mandatory_scope(ctx, query):
    command = getattr(ctx, query + '_cmd')
    page = await getattr(ctx, query).execute(cmd=command)
    item = ctx.item if query == 'personal' else ctx.wallet_item
    assert page.items == [item]
    assert page.next_cursor is None
    call = reader(ctx, query).await_args
    assert call.kwargs == {'user_id': ctx.user.id, 'filters': command.filters, 'limit': 21, 'cursor': None}
    if query == 'wallet':
        assert call.args == (ctx.wallet_id,)
    assert_read_only(ctx)


@pytest.mark.parametrize('query', ['personal', 'wallet'])
@pytest.mark.parametrize('status', [None, UserStatusEnum.PENDING_CONFIRMATION, UserStatusEnum.SUSPENDED, UserStatusEnum.CLOSED])
async def test_missing_or_inactive_user_cannot_read(ctx, query, status):
    ctx.uow.users.get_by_id.return_value = None if status is None else replace(ctx.user, status=status)
    with pytest.raises(UserNotFoundError if status is None else UserInactiveError):
        await getattr(ctx, query).execute(getattr(ctx, query + '_cmd'))
    reader(ctx, query).assert_not_awaited()
    assert_read_only(ctx)


@pytest.mark.parametrize('query', ['personal', 'wallet'])
async def test_invalid_actor_rejected_before_uow(ctx, query):
    with pytest.raises(TypeError):
        await getattr(ctx, query).execute(replace(getattr(ctx, query + '_cmd'), user_id='uuid'))
    ctx.uow.__aenter__.assert_not_awaited()


async def test_invalid_wallet_id_rejected_before_uow(ctx):
    with pytest.raises(TypeError):
        await ctx.wallet.execute(replace(ctx.wallet_cmd, wallet_id=None))
    ctx.uow.__aenter__.assert_not_awaited()


async def test_missing_or_foreign_wallet_maps_to_not_found(ctx):
    reader(ctx, 'wallet').return_value = None
    with pytest.raises(WalletNotFoundError):
        await ctx.wallet.execute(ctx.wallet_cmd)
    assert_read_only(ctx)


@pytest.mark.parametrize('query', ['personal', 'wallet'])
@pytest.mark.parametrize('size', [0, 1, 2])
async def test_empty_or_last_page_has_no_cursor(ctx, query, size):
    item = ctx.item if query == 'personal' else ctx.wallet_item
    reader(ctx, query).return_value = [replace(item, id=UUID(int=value)) for value in range(size)]
    page = await getattr(ctx, query).execute(replace(getattr(ctx, query + '_cmd'), limit=2))
    assert len(page.items) == size
    assert page.next_cursor is None


@pytest.mark.parametrize('query', ['personal', 'wallet'])
async def test_keyset_cursor_uses_last_delivered_journal_with_timestamp_ties(ctx, query, now):
    item = ctx.item if query == 'personal' else ctx.wallet_item
    items = [replace(item, id=UUID(int=value)) for value in (30, 20, 10)]
    reader(ctx, query).return_value = items
    command = replace(getattr(ctx, query + '_cmd'), limit=2)
    first = await getattr(ctx, query).execute(command)
    assert first.items == items[:2]
    position = ctx.codec.decode(first.next_cursor, context=cursor_context(command, query))
    assert position == CursorPosition(timestamp=now, id=UUID(int=20))
    reader(ctx, query).return_value = items[2:]
    second = await getattr(ctx, query).execute(replace(command, cursor=first.next_cursor))
    assert second.items == items[2:]
    assert second.next_cursor is None
    assert reader(ctx, query).await_args.kwargs['cursor'] == position
    assert_read_only(ctx)


@pytest.mark.parametrize('query', ['personal', 'wallet'])
@pytest.mark.parametrize('limit', [0, 101, True, 1.5, None])
async def test_invalid_limit_rejected_before_uow(ctx, query, limit):
    with pytest.raises(InvalidPaginationError):
        await getattr(ctx, query).execute(replace(getattr(ctx, query + '_cmd'), limit=limit))
    ctx.uow.__aenter__.assert_not_awaited()


@pytest.mark.parametrize('query', ['personal', 'wallet'])
async def test_wrong_filter_type_rejected_before_uow(ctx, query):
    with pytest.raises(InvalidTransactionFilterError):
        await getattr(ctx, query).execute(replace(getattr(ctx, query + '_cmd'), filters={}))
    ctx.uow.__aenter__.assert_not_awaited()


@pytest.mark.parametrize('query', ['personal', 'wallet'])
async def test_invalid_cursor_never_reaches_reader(ctx, query):
    with pytest.raises(InvalidCursorError):
        await getattr(ctx, query).execute(replace(getattr(ctx, query + '_cmd'), cursor='broken'))
    reader(ctx, query).assert_not_awaited()


@pytest.mark.parametrize('query', ['personal', 'wallet'])
@pytest.mark.parametrize('field', ['kind', 'currency', 'direction', 'posted_from', 'posted_to', 'wallet_id', 'user_id'])
async def test_cursor_bound_to_all_filters_wallet_and_actor(ctx, query, field, now):
    command = getattr(ctx, query + '_cmd')
    token = ctx.codec.encode(CursorPosition(timestamp=now, id=ctx.item.id), context=cursor_context(command, query))
    command = replace(command, cursor=token)
    if field == 'user_id':
        other = replace(ctx.user, id=uuid4())
        ctx.uow.users.get_by_id.return_value = other
        command = replace(command, user_id=other.id)
    elif field == 'wallet_id' and query == 'wallet':
        command = replace(command, wallet_id=uuid4())
    else:
        values = {
            'kind': LedgerTransactionKindEnum.SANDBOX_TOPUP, 'currency': CurrencyEnum.EUR,
            'direction': TransactionDirectionEnum.INCOMING, 'posted_from': now - timedelta(days=1),
            'posted_to': now + timedelta(days=1), 'wallet_id': uuid4(),
        }
        command = replace(command, filters=replace(command.filters, **{field: values[field]}))
    with pytest.raises(InvalidCursorError):
        await getattr(ctx, query).execute(command)
    reader(ctx, query).assert_not_awaited()


async def test_cursor_cannot_move_between_personal_and_wallet_history(ctx, now):
    selected = replace(ctx.personal_cmd, filters=MyTransactionsFilter(wallet_id=ctx.wallet_id))
    token = ctx.codec.encode(CursorPosition(timestamp=now, id=ctx.item.id), context=cursor_context(selected, 'personal'))
    with pytest.raises(InvalidCursorError):
        await ctx.wallet.execute(replace(ctx.wallet_cmd, cursor=token))
    reader(ctx, 'wallet').assert_not_awaited()


@pytest.mark.parametrize('query', ['personal', 'wallet'])
async def test_normalized_dates_and_changed_page_size_keep_cursor_valid(ctx, query, now):
    command = getattr(ctx, query + '_cmd')
    command = replace(command, filters=replace(command.filters, posted_from=now))
    token = ctx.codec.encode(CursorPosition(timestamp=now, id=ctx.item.id), context=cursor_context(command, query))
    command = replace(command, filters=replace(command.filters, posted_from=now.astimezone(timezone(timedelta(hours=5)))))
    await getattr(ctx, query).execute(replace(command, cursor=token, limit=100))
    assert reader(ctx, query).await_args.kwargs['limit'] == 101


async def test_all_filter_fields_are_forwarded_with_actor(ctx, now):
    filters = MyTransactionsFilter(
        wallet_id=ctx.wallet_id, kind=LedgerTransactionKindEnum.P2P_TRANSFER, currency=CurrencyEnum.USD,
        direction=TransactionDirectionEnum.OUTGOING, posted_from=now, posted_to=now + timedelta(days=1),
    )
    await ctx.personal.execute(replace(ctx.personal_cmd, filters=filters))
    reader(ctx, 'personal').assert_awaited_once_with(user_id=ctx.user.id, filters=filters, limit=21, cursor=None)


async def test_internal_journal_remains_one_row_from_one_reader_call(ctx):
    internal = replace(ctx.item, direction=TransactionDirectionEnum.INTERNAL)
    reader(ctx, 'personal').return_value = [internal]
    page = await ctx.personal.execute(ctx.personal_cmd)
    assert page.items == [internal]
    reader(ctx, 'personal').assert_awaited_once()
    reader(ctx, 'wallet').assert_not_awaited()


def test_counterparty_follows_selected_wallet_and_top_up_has_none(ctx):
    assert ctx.wallet_item.counterparty_wallet_id == ctx.item.receiver_wallet_id
    received = replace(ctx.wallet_item, wallet_id=ctx.item.receiver_wallet_id, direction=TransactionDirectionEnum.INCOMING)
    assert received.counterparty_wallet_id == ctx.item.sender_wallet_id
    top_up = replace(received, sender_wallet_id=None, source_type=LedgerTransactionKindEnum.SANDBOX_TOPUP)
    assert top_up.counterparty_wallet_id is None


@pytest.mark.parametrize('query', ['personal', 'wallet'])
async def test_reader_failure_propagates_and_exits_uow(ctx, query):
    error = RuntimeError('reader unavailable')
    reader(ctx, query).side_effect = error
    with pytest.raises(RuntimeError, match='reader unavailable'):
        await getattr(ctx, query).execute(getattr(ctx, query + '_cmd'))
    assert ctx.uow.__aexit__.await_args.args[1] is error
    assert_read_only(ctx)


@pytest.mark.parametrize('filter_type', [WalletTransactionFilter, MyTransactionsFilter])
@pytest.mark.parametrize(('field', 'value'), [
    ('kind', 'p2p_transfer'), ('currency', 'USD'), ('direction', 'incoming'),
    ('posted_from', 'date'), ('posted_to', 1),
])
def test_filters_reject_untyped_values(filter_type, field, value):
    with pytest.raises(InvalidTransactionFilterError):
        filter_type(**{field: value})


@pytest.mark.parametrize('field', ['posted_from', 'posted_to'])
def test_naive_dates_are_rejected(now, field):
    with pytest.raises(InvalidTransactionFilterError):
        MyTransactionsFilter(**{field: now.replace(tzinfo=None)})


@pytest.mark.parametrize('offset', [0, -1])
def test_date_range_requires_increasing_end(now, offset):
    with pytest.raises(InvalidTransactionFilterError):
        MyTransactionsFilter(posted_from=now, posted_to=now + timedelta(days=offset))


def test_wallet_filter_requires_uuid():
    with pytest.raises(InvalidTransactionFilterError):
        MyTransactionsFilter(wallet_id='uuid')


def test_internal_direction_is_only_valid_for_unfiltered_global_history():
    assert MyTransactionsFilter(direction=TransactionDirectionEnum.INTERNAL).direction is TransactionDirectionEnum.INTERNAL
    with pytest.raises(InvalidTransactionFilterError):
        MyTransactionsFilter(wallet_id=uuid4(), direction=TransactionDirectionEnum.INTERNAL)
    with pytest.raises(InvalidTransactionFilterError):
        WalletTransactionFilter(direction=TransactionDirectionEnum.INTERNAL)

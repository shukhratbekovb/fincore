from dataclasses import replace
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from backend.application.auth.errors import UserInactiveError
from backend.application.share.dtos.pagination import CursorPosition
from backend.application.share.errors import InvalidCursorError, InvalidPaginationError
from backend.application.transfer.dtos.base import TransferDTO
from backend.application.transfer.dtos.filters import TransferDirectionEnum, TransferFilter
from backend.application.transfer.dtos.get_my_transfers import GetMyTransfersCommand
from backend.application.transfer.dtos.get_transfer import GetTransferCommand
from backend.application.transfer.errors import InvalidTransferFilterError, TransferNotFoundError
from backend.application.transfer.queries.get_my_transfers import GetMyTransfersQuery
from backend.application.transfer.queries.get_transfer import GetTransferQuery
from backend.application.user.errors import UserNotFoundError
from backend.domain.share.enums import CurrencyEnum
from backend.domain.transfer.enums import TransferRejectionCodeEnum, TransferStatusEnum
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, Username
from backend.infrastructure.pagination.cursor import HMACCursorCodec


@pytest.fixture
def ctx(now):
    user = User.register(Username('alice'), Email('alice@example.com'))
    user.activate()
    item = TransferDTO(
        id=UUID(int=100), sender_wallet_id=uuid4(), receiver_wallet_id=uuid4(),
        amount_minor=10000, currency=CurrencyEnum.USD, status=TransferStatusEnum.COMPLETED,
        direction=TransferDirectionEnum.OUTGOING, created_at=now, completed_at=now,
    )
    uow = AsyncMock()
    uow.users = SimpleNamespace(get_by_id=AsyncMock(return_value=user), get_by_id_for_update=AsyncMock())
    uow.transfer_reader = SimpleNamespace(
        get_by_id_for_user=AsyncMock(return_value=item), list_by_user_id=AsyncMock(return_value=[item]),
    )
    codec = HMACCursorCodec(b'transfer-query-test-only-key-12345')
    return SimpleNamespace(
        user=user, item=item, uow=uow, codec=codec,
        detail=GetTransferQuery(uow), listing=GetMyTransfersQuery(uow, codec),
        detail_cmd=GetTransferCommand(user.id, item.id), list_cmd=GetMyTransfersCommand(user.id),
    )


def assert_read_only(ctx):
    ctx.uow.commit.assert_not_awaited()
    ctx.uow.users.get_by_id_for_update.assert_not_awaited()
    ctx.uow.transfers.add.assert_not_awaited()
    ctx.uow.ledger_transactions.add.assert_not_awaited()
    ctx.uow.wallet_balances.save.assert_not_awaited()


async def test_detail_returns_scoped_dto_without_writes(ctx):
    before = vars(ctx.item).copy()
    result = await ctx.detail.execute(cmd=ctx.detail_cmd)
    assert result is ctx.item
    assert vars(result) == before
    ctx.uow.transfer_reader.get_by_id_for_user.assert_awaited_once_with(ctx.item.id, user_id=ctx.user.id)
    assert not any(name in vars(result) for name in ('email', 'password_hash', 'balance_minor', 'sender_user_id'))
    assert_read_only(ctx)


async def test_reader_none_maps_missing_or_foreign_detail_to_same_error(ctx):
    ctx.uow.transfer_reader.get_by_id_for_user.return_value = None
    with pytest.raises(TransferNotFoundError):
        await ctx.detail.execute(ctx.detail_cmd)
    assert_read_only(ctx)


@pytest.mark.parametrize('query', ['detail', 'listing'])
@pytest.mark.parametrize('status', [None, UserStatusEnum.PENDING_CONFIRMATION, UserStatusEnum.SUSPENDED, UserStatusEnum.CLOSED])
async def test_missing_or_inactive_user_never_reaches_reader(ctx, query, status):
    ctx.uow.users.get_by_id.return_value = None if status is None else replace(ctx.user, status=status)
    command = ctx.detail_cmd if query == 'detail' else ctx.list_cmd
    with pytest.raises(UserNotFoundError if status is None else UserInactiveError):
        await getattr(ctx, query).execute(command)
    ctx.uow.transfer_reader.get_by_id_for_user.assert_not_awaited()
    ctx.uow.transfer_reader.list_by_user_id.assert_not_awaited()
    assert_read_only(ctx)


@pytest.mark.parametrize('query', ['detail', 'listing'])
async def test_invalid_actor_id_is_rejected_before_uow(ctx, query):
    command = ctx.detail_cmd if query == 'detail' else ctx.list_cmd
    with pytest.raises(TypeError):
        await getattr(ctx, query).execute(replace(command, user_id='uuid'))
    ctx.uow.__aenter__.assert_not_awaited()


async def test_detail_rejects_invalid_transfer_id_before_uow(ctx):
    with pytest.raises(TypeError):
        await ctx.detail.execute(replace(ctx.detail_cmd, transfer_id=None))
    ctx.uow.__aenter__.assert_not_awaited()


async def test_default_list_fetches_extra_row_and_returns_page(ctx):
    result = await ctx.listing.execute(ctx.list_cmd)
    assert result.items == [ctx.item]
    assert result.next_cursor is None
    ctx.uow.transfer_reader.list_by_user_id.assert_awaited_once_with(
        user_id=ctx.user.id, filters=TransferFilter(), limit=21, cursor=None,
    )
    assert_read_only(ctx)


@pytest.mark.parametrize('size', [0, 1, 2])
async def test_final_or_empty_page_has_no_next_cursor(ctx, size):
    ctx.uow.transfer_reader.list_by_user_id.return_value = [replace(ctx.item, id=uuid4()) for _ in range(size)]
    result = await ctx.listing.execute(replace(ctx.list_cmd, limit=2))
    assert len(result.items) == size
    assert result.next_cursor is None


async def test_next_cursor_uses_last_returned_row_and_not_lookahead(ctx, now):
    items = [replace(ctx.item, id=UUID(int=value)) for value in (30, 20, 10)]
    ctx.uow.transfer_reader.list_by_user_id.return_value = items
    command = replace(ctx.list_cmd, limit=2)
    first = await ctx.listing.execute(command)
    assert first.items == items[:2]
    position = ctx.codec.decode(first.next_cursor, context=ctx.listing._cursor_context(command))
    assert position.id == UUID(int=20)
    assert position.timestamp == now
    ctx.uow.transfer_reader.list_by_user_id.return_value = [items[2]]
    second = await ctx.listing.execute(replace(command, cursor=first.next_cursor))
    assert second.items == [items[2]]
    assert second.next_cursor is None
    assert ctx.uow.transfer_reader.list_by_user_id.await_args.kwargs['cursor'] == position
    assert_read_only(ctx)


@pytest.mark.parametrize('direction', list(TransferDirectionEnum))
async def test_direction_and_other_filters_are_forwarded_with_mandatory_actor(ctx, now, direction):
    filters = TransferFilter(
        wallet_id=ctx.item.sender_wallet_id, currency=CurrencyEnum.USD,
        status=TransferStatusEnum.COMPLETED, direction=direction,
        created_from=now - timedelta(days=1), created_to=now + timedelta(days=1),
    )
    await ctx.listing.execute(replace(ctx.list_cmd, filters=filters, limit=100))
    ctx.uow.transfer_reader.list_by_user_id.assert_awaited_once_with(
        user_id=ctx.user.id, filters=filters, limit=101, cursor=None,
    )


@pytest.mark.parametrize('limit', [0, 101, -1, True, False, 1.5, '20', None])
async def test_invalid_page_size_rejected_before_uow(ctx, limit):
    with pytest.raises(InvalidPaginationError):
        await ctx.listing.execute(replace(ctx.list_cmd, limit=limit))
    ctx.uow.__aenter__.assert_not_awaited()


async def test_invalid_filter_object_rejected_before_uow(ctx):
    with pytest.raises(InvalidTransferFilterError):
        await ctx.listing.execute(replace(ctx.list_cmd, filters={}))
    ctx.uow.__aenter__.assert_not_awaited()


@pytest.mark.parametrize('cursor', ['', 'broken', 1, 'x' * 2049])
async def test_invalid_cursor_never_reaches_reader(ctx, cursor):
    with pytest.raises(InvalidCursorError):
        await ctx.listing.execute(replace(ctx.list_cmd, cursor=cursor))
    ctx.uow.transfer_reader.list_by_user_id.assert_not_awaited()
    assert_read_only(ctx)


@pytest.mark.parametrize('field', ['wallet_id', 'currency', 'status', 'direction', 'created_from', 'created_to', 'user_id'])
async def test_cursor_is_bound_to_actor_and_all_filters(ctx, now, field):
    token = ctx.codec.encode(
        top_position(ctx), context=ctx.listing._cursor_context(ctx.list_cmd),
    )
    values = {
        'wallet_id': uuid4(), 'currency': CurrencyEnum.EUR, 'status': TransferStatusEnum.REJECTED,
        'direction': TransferDirectionEnum.INTERNAL, 'created_from': now - timedelta(days=1),
        'created_to': now + timedelta(days=1),
    }
    command = replace(ctx.list_cmd, cursor=token)
    if field == 'user_id':
        other_user = replace(ctx.user, id=uuid4())
        ctx.uow.users.get_by_id.return_value = other_user
        command = replace(command, user_id=other_user.id)
    else:
        command = replace(command, filters=TransferFilter(**{field: values[field]}))
    with pytest.raises(InvalidCursorError):
        await ctx.listing.execute(command)
    ctx.uow.transfer_reader.list_by_user_id.assert_not_awaited()


def top_position(ctx):
    return CursorPosition(timestamp=ctx.item.created_at, id=ctx.item.id)


async def test_equivalent_timezone_filters_can_reuse_cursor_and_change_page_size(ctx, now):
    command = replace(ctx.list_cmd, filters=TransferFilter(created_from=now))
    token = ctx.codec.encode(top_position(ctx), context=ctx.listing._cursor_context(command))
    local = now.astimezone(timezone(timedelta(hours=5)))
    await ctx.listing.execute(replace(command, filters=TransferFilter(created_from=local), cursor=token, limit=1))
    assert ctx.uow.transfer_reader.list_by_user_id.await_args.kwargs['cursor'] == top_position(ctx)


async def test_query_does_not_confuse_rejected_transfer_with_posted_movement(ctx):
    rejected = replace(
        ctx.item, status=TransferStatusEnum.REJECTED, completed_at=None,
        rejection_code=TransferRejectionCodeEnum.INSUFFICIENT_FUNDS,
    )
    ctx.uow.transfer_reader.get_by_id_for_user.return_value = rejected
    ctx.uow.transfer_reader.list_by_user_id.return_value = [rejected]
    assert await ctx.detail.execute(ctx.detail_cmd) == rejected
    page = await ctx.listing.execute(ctx.list_cmd)
    assert page.items == [rejected]
    assert_read_only(ctx)


async def test_internal_transfer_is_one_item_from_one_scoped_read(ctx):
    internal = replace(ctx.item, direction=TransferDirectionEnum.INTERNAL)
    ctx.uow.transfer_reader.list_by_user_id.return_value = [internal]
    page = await ctx.listing.execute(ctx.list_cmd)
    assert page.items == [internal]
    assert page.next_cursor is None
    ctx.uow.transfer_reader.list_by_user_id.assert_awaited_once()
    ctx.uow.transfer_reader.get_by_id_for_user.assert_not_awaited()
    assert_read_only(ctx)


@pytest.mark.parametrize('query', ['detail', 'listing'])
async def test_reader_failure_propagates_and_exits_uow(ctx, query):
    method = ctx.uow.transfer_reader.get_by_id_for_user if query == 'detail' else ctx.uow.transfer_reader.list_by_user_id
    error = RuntimeError('reader unavailable')
    method.side_effect = error
    with pytest.raises(RuntimeError, match='reader unavailable'):
        await getattr(ctx, query).execute(ctx.detail_cmd if query == 'detail' else ctx.list_cmd)
    assert ctx.uow.__aexit__.await_args.args[1] is error
    assert_read_only(ctx)


@pytest.mark.parametrize(('field', 'value'), [
    ('wallet_id', 'uuid'), ('currency', 'USD'), ('status', 'completed'), ('direction', 'incoming'),
    ('created_from', '2026-11-11'), ('created_to', 1),
])
def test_filter_rejects_untyped_values(field, value):
    with pytest.raises(InvalidTransferFilterError):
        TransferFilter(**{field: value})


@pytest.mark.parametrize('field', ['created_from', 'created_to'])
def test_filter_rejects_naive_dates(now, field):
    with pytest.raises(InvalidTransferFilterError):
        TransferFilter(**{field: now.replace(tzinfo=None)})


@pytest.mark.parametrize('offset', [0, -1])
def test_filter_requires_increasing_date_range(now, offset):
    with pytest.raises(InvalidTransferFilterError):
        TransferFilter(created_from=now, created_to=now + timedelta(days=offset))

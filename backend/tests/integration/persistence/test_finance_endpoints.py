import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func, text, update, delete
from sqlalchemy.exc import IntegrityError

from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Username, Email, HashedPassword
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork
from backend.infrastructure.db.sqlalchemy.models import (
    SqlAlchemySandboxOperatorModel, SqlAlchemyTransferModel, SqlAlchemySandboxTopUpModel,
    SqlAlchemyLedgerTransactionModel, SqlAlchemyLedgerEntryModel, SqlAlchemyIdempotencyModel,
    SqlAlchemyWalletBalanceModel,
)
from backend.infrastructure.security.token_issuer import JWTTokenIssuer
from backend.infrastructure.settings import Settings, get_settings
from backend.main import app
from backend.presentation.api.v1.dependencies.core import get_clock


@pytest.fixture
async def ctx(session_factory, redis_context, monkeypatch, now):
    users = [User.created_by_admin(Username(name), Email(name + '@example.com'), HashedPassword('test-hash'))
             for name in ('operator', 'alice', 'bobby', 'outsider')]
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        for user in users:
            await uow.users.add(user)
        uow.session.add(SqlAlchemySandboxOperatorModel(user_id=users[0].id))
        for currency in CurrencyEnum:
            await uow.ledger_accounts.add(LedgerAccount.for_sandbox_funding(currency=currency, now=now))
        await uow.commit()
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test',
                        jwt_secret_key='finance-integration-tests-key-only-' * 2, sandbox_enabled=True)
    issuer = JWTTokenIssuer(settings)
    headers = [{'Authorization': 'Bearer ' + issuer.encode(user.id)} for user in users]
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setitem(app.dependency_overrides, get_clock, lambda: SimpleNamespace(now=lambda: now))
    monkeypatch.setattr(app.state, 'session_factory', session_factory, raising=False)
    monkeypatch.setattr(app.state, 'rate_limiter', redis_context.limiter, raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        async def wallet(actor=1, currency='USD'):
            response = await client.post('/v1/wallets', headers=headers[actor], json={'name': 'Main', 'currency': currency})
            assert response.status_code == 201, response.text
            return response.json()['wallet_id']
        a, b, own = await wallet(), await wallet(2), await wallet()
        yield SimpleNamespace(client=client, factory=session_factory, users=users, headers=headers,
                              settings=settings, a=a, b=b, own=own, wallet=wallet, redis=redis_context)


async def top_up(ctx, wallet=None, amount='50000', key=None):
    return await ctx.client.post('/v1/sandbox/top-ups', headers={**ctx.headers[0], 'Idempotency-Key': key or str(uuid4())},
                                 json={'wallet_id': wallet or ctx.a, 'amount_minor': amount, 'currency': 'USD'})


async def transfer(ctx, sender=None, receiver=None, amount='10000', key=None, actor=1, currency='USD'):
    return await ctx.client.post('/v1/transfers', headers={**ctx.headers[actor], 'Idempotency-Key': key or str(uuid4())},
                                 json={'sender_wallet_id': sender or ctx.a, 'receiver_wallet_id': receiver or ctx.b,
                                       'amount_minor': amount, 'currency': currency})


async def balance(ctx, wallet=None, actor=1):
    response = await ctx.client.get('/v1/wallets/' + (wallet or ctx.a) + '/balance', headers=ctx.headers[actor])
    assert response.status_code == 200, response.text
    return response.json()


async def test_all_eight_endpoints_and_ledger_conservation(ctx):
    funded = await top_up(ctx)
    assert funded.status_code == 201, funded.text
    moved = await transfer(ctx)
    assert moved.status_code == 201, moved.text
    tid = moved.json()['transfer_id']
    a, b = await balance(ctx), await balance(ctx, ctx.b, actor=2)
    assert a['posted_minor'] == a['available_minor'] == a['spendable_minor'] == '40000'
    assert a['version'] == '2' and b['posted_minor'] == '10000'
    for actor, direction in ((1, 'outgoing'), (2, 'incoming')):
        response = await ctx.client.get('/v1/transfers/' + tid, headers=ctx.headers[actor])
        assert response.status_code == 200 and response.json()['direction'] == direction
        assert response.json()['amount_minor'] == '10000'
        assert response.headers['cache-control'] == 'no-store'
    listed = await ctx.client.get('/v1/transfers', headers=ctx.headers[1])
    assert [item['id'] for item in listed.json()['items']] == [tid]
    history = await ctx.client.get('/v1/wallets/' + ctx.a + '/transactions', headers=ctx.headers[1])
    assert history.status_code == 200 and len(history.json()['items']) == 2
    assert {item['source_type'] for item in history.json()['items']} == {'sandbox_topup', 'p2p_transfer'}
    personal = await ctx.client.get('/v1/users/me/transactions', headers=ctx.headers[1])
    assert personal.status_code == 200 and len(personal.json()['items']) == 2
    summary = await ctx.client.get('/v1/users/me/balances', headers=ctx.headers[1])
    assert summary.status_code == 200
    assert summary.json()['totals'] == [{'currency': 'USD', 'posted_minor': '40000', 'available_minor': '40000', 'spendable_minor': '40000'}]
    async with ctx.factory() as session:
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyLedgerTransactionModel)) == 2
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyLedgerEntryModel)) == 4
        assert await session.scalar(select(func.sum(SqlAlchemyWalletBalanceModel.posted_minor))) == 50000


async def test_replay_conflict_and_concurrent_same_key_do_not_duplicate_money(ctx):
    first = await top_up(ctx, key='fund-once')
    second = await top_up(ctx, key='fund-once')
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    conflict = await top_up(ctx, amount='50001', key='fund-once')
    assert conflict.status_code == 409 and conflict.json()['detail']['code'] == 'idempotency_conflict'
    results = await asyncio.gather(*(transfer(ctx, key='move-once') for _ in range(4)))
    assert all(response.status_code == 201 for response in results), [response.text for response in results]
    assert len({response.json()['transfer_id'] for response in results}) == 1
    assert (await balance(ctx))['posted_minor'] == '40000'


async def test_concurrent_spending_and_opposite_transfers(ctx):
    assert (await top_up(ctx, amount='15000')).status_code == 201
    results = await asyncio.gather(transfer(ctx, amount='10000'), transfer(ctx, receiver=ctx.own, amount='10000'))
    assert sorted(response.status_code for response in results) == [201, 422]
    assert (await balance(ctx))['posted_minor'] == '5000'
    assert (await top_up(ctx, wallet=ctx.b, amount='20000')).status_code == 201
    results = await asyncio.gather(
        transfer(ctx, amount='1000'), transfer(ctx, sender=ctx.b, receiver=ctx.a, amount='1000', actor=2),
    )
    assert all(response.status_code == 201 for response in results), [response.text for response in results]
    async with ctx.factory() as session:
        assert await session.scalar(select(func.sum(SqlAlchemyWalletBalanceModel.posted_minor))) == 35000


async def test_acl_auth_filters_and_cursor_pagination(ctx):
    assert (await top_up(ctx)).status_code == 201
    transfers = [await transfer(ctx, receiver=ctx.own, amount='100') for _ in range(3)]
    assert all(response.status_code == 201 for response in transfers)
    tid = transfers[0].json()['transfer_id']
    for suffix in (tid, str(uuid4())):
        response = await ctx.client.get('/v1/transfers/' + suffix, headers=ctx.headers[3])
        assert response.status_code == 404 and response.json()['detail']['code'] == 'transfer_not_found'
    for suffix in ('/balance', '/transactions'):
        response = await ctx.client.get('/v1/wallets/' + ctx.a + suffix, headers=ctx.headers[3])
        assert response.status_code == 404
        assert (await ctx.client.get('/v1/wallets/' + ctx.a + suffix)).status_code == 401
    for path in ('/v1/transfers', '/v1/users/me/transactions'):
        ids, cursor = [], None
        while True:
            params = {'limit': 1}
            if cursor: params['cursor'] = cursor
            response = await ctx.client.get(path, headers=ctx.headers[1], params=params)
            assert response.status_code == 200, response.text
            ids += [item['id'] for item in response.json()['items']]
            cursor = response.json()['next_cursor']
            if not cursor: break
            wrong = await ctx.client.get(path, headers=ctx.headers[3], params={'cursor': cursor})
            assert wrong.status_code == 422
            changed = await ctx.client.get(path, headers=ctx.headers[1], params={'cursor': cursor, 'currency': 'EUR'})
            assert changed.status_code == 422
        assert len(ids) == len(set(ids)) == (3 if path == '/v1/transfers' else 4)
    internal = await ctx.client.get('/v1/transfers', headers=ctx.headers[1], params={'direction': 'internal', 'wallet_id': ctx.a})
    assert len(internal.json()['items']) == 3
    foreign_filter = await ctx.client.get('/v1/transfers', headers=ctx.headers[3], params={'wallet_id': ctx.a})
    assert foreign_filter.json()['items'] == []
    scoped = await ctx.client.get('/v1/users/me/transactions', headers=ctx.headers[1], params={'wallet_id': ctx.own, 'direction': 'incoming'})
    assert len(scoped.json()['items']) == 3
    wallet_page = await ctx.client.get('/v1/wallets/' + ctx.a + '/transactions', headers=ctx.headers[1], params={'limit': 1})
    cursor = wallet_page.json()['next_cursor']
    assert cursor
    next_page = await ctx.client.get('/v1/wallets/' + ctx.a + '/transactions', headers=ctx.headers[1], params={'limit': 1, 'cursor': cursor})
    assert next_page.status_code == 200 and next_page.json()['items'][0]['id'] != wallet_page.json()['items'][0]['id']


async def test_role_flag_limits_invalid_payload_and_read_policy(ctx):
    response = await ctx.client.post('/v1/sandbox/top-ups', headers={**ctx.headers[1], 'Idempotency-Key': 'denied'},
                                     json={'wallet_id': ctx.a, 'amount_minor': 100, 'currency': 'USD'})
    assert response.status_code == 403 and response.json()['detail']['code'] == 'sandbox_operator_required'
    ctx.settings.sandbox_enabled = False
    assert (await top_up(ctx)).json()['detail']['code'] == 'sandbox_disabled'
    ctx.settings.sandbox_enabled = True
    ctx.settings.sandbox_max_amount_minor = 100
    assert (await top_up(ctx)).json()['detail']['code'] == 'top_up_limit_exceeded'
    ctx.settings.sandbox_max_amount_minor = 2 ** 63 - 1
    for amount in (True, 1.5, 0, -1, '1.5', str(2 ** 63)):
        assert (await top_up(ctx, amount=amount)).status_code == 422
    no_key = await ctx.client.post('/v1/transfers', headers=ctx.headers[1], json={
        'sender_wallet_id': ctx.a, 'receiver_wallet_id': ctx.b, 'amount_minor': 100, 'currency': 'USD'})
    assert no_key.status_code == 422
    assert (await transfer(ctx, amount=1)).json()['detail']['code'] == 'insufficient_funds'
    assert (await transfer(ctx, receiver=ctx.a, amount=1)).json()['detail']['code'] == 'same_wallet_transfer'
    eur = await ctx.wallet(currency='EUR')
    assert (await transfer(ctx, receiver=eur, amount=1)).json()['detail']['code'] == 'transfer_currency_mismatch'
    assert (await transfer(ctx, actor=3, amount=1)).status_code == 404
    assert (await top_up(ctx)).status_code == 201
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        wallet = await uow.wallets.get_by_id_for_update(UUID(ctx.a))
        wallet.freeze()
        await uow.wallets.save(wallet)
        await uow.commit()
    assert (await balance(ctx))['spendable_minor'] == '0'
    summary = await ctx.client.get('/v1/users/me/balances', headers=ctx.headers[1])
    usd = next(total for total in summary.json()['totals'] if total['currency'] == 'USD')
    assert usd['posted_minor'] == '50000'
    assert usd['spendable_minor'] == '0'
    assert (await transfer(ctx)).json()['detail']['code'] == 'wallet_not_active'
    for path in ('/v1/transfers?limit=0', '/v1/transfers?created_from=2026-11-10T00:00:00',
                 '/v1/users/me/transactions?wallet_id=' + ctx.a + '&direction=internal'):
        assert (await ctx.client.get(path, headers=ctx.headers[1])).status_code == 422


async def test_fault_between_journal_and_balance_rolls_back_entire_command(ctx, monkeypatch):
    from backend.infrastructure.db.sqlalchemy.repository.wallet_balance import SqlAlchemyWalletBalanceRepository
    assert (await top_up(ctx)).status_code == 201
    original = SqlAlchemyWalletBalanceRepository.save
    async def fail(self, balance):
        await original(self, balance)
        raise RuntimeError('injected failure')
    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyWalletBalanceRepository, 'save', fail)
        with pytest.raises(RuntimeError, match='injected failure'):
            await transfer(ctx, key='retry-after-rollback')
    assert (await balance(ctx))['posted_minor'] == '50000'
    async with ctx.factory() as session:
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyTransferModel)) == 0
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyIdempotencyModel)) == 1
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyLedgerEntryModel)) == 2
    assert (await transfer(ctx, key='retry-after-rollback')).status_code == 201


async def test_db_rejects_ledger_edits_and_unfinished_claim(ctx):
    assert (await top_up(ctx)).status_code == 201
    for stmt in (
        update(SqlAlchemyLedgerEntryModel).values(amount_minor=1),
        delete(SqlAlchemyLedgerTransactionModel), update(SqlAlchemySandboxTopUpModel).values(amount_minor=1),
    ):
        with pytest.raises(IntegrityError):
            async with ctx.factory() as session:
                await session.execute(stmt)
                await session.commit()
    with pytest.raises(IntegrityError):
        async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
            await uow.idempotency.claim(user_id=ctx.users[1].id, scope='transfer.create', key='unfinished', payload_hash='a' * 64)
            await uow.commit()


async def test_large_money_serialization_summary_and_corruption_visibility(ctx):
    max_amount = str(2 ** 63 - 1)
    assert (await top_up(ctx, amount=max_amount)).status_code == 201
    assert (await top_up(ctx, wallet=ctx.own, amount=max_amount)).status_code == 201
    summary = await ctx.client.get('/v1/users/me/balances', headers=ctx.headers[1])
    assert summary.json()['totals'][0]['posted_minor'] == str(2 * (2 ** 63 - 1))
    assert (await top_up(ctx, amount=1)).json()['detail']['code'] == 'wallet_balance_overflow'
    async with ctx.factory() as session:
        await session.execute(delete(SqlAlchemyWalletBalanceModel).where(SqlAlchemyWalletBalanceModel.wallet_id == UUID(ctx.a)))
        await session.commit()
    response = await ctx.client.get('/v1/wallets/' + ctx.a + '/balance', headers=ctx.headers[1])
    assert response.status_code == 500 and response.json()['detail']['code'] == 'wallet_accounting_state_error'
    assert (await ctx.client.get('/v1/users/me/balances', headers=ctx.headers[1])).status_code == 500
    assert (await ctx.client.get('/v1/wallets/' + ctx.a + '/balance', headers=ctx.headers[3])).status_code == 404


async def test_bounded_key_contention_rolls_back_savepoint_and_allows_retry(ctx):
    assert (await top_up(ctx)).status_code == 201
    async with SqlAlchemyUnitOfWork(ctx.factory) as owner:
        await owner.idempotency.claim(user_id=ctx.users[1].id, scope='transfer.create', key='held-key', payload_hash='a' * 64)
        response = await transfer(ctx, key='held-key')
        assert response.status_code == 409 and response.json()['detail']['code'] == 'idempotency_in_progress'
    assert (await transfer(ctx, key='held-key')).status_code == 201


async def test_db_rejects_completed_source_without_a_journal(ctx, now):
    from backend.domain.transfer.entities import Transfer
    source = Transfer.create(sender_wallet_id=UUID(ctx.a), receiver_wallet_id=UUID(ctx.b),
                             amount_minor=1, currency=CurrencyEnum.USD, now=now)
    source.complete(now=now)
    with pytest.raises(IntegrityError):
        async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
            await uow.transfers.add(source)
            await uow.commit()


async def test_db_rejects_a_half_journal_and_preserves_replay_identity(ctx, now):
    from backend.domain.transfer.entities import Transfer
    source = Transfer.create(sender_wallet_id=UUID(ctx.a), receiver_wallet_id=UUID(ctx.b),
                             amount_minor=1, currency=CurrencyEnum.USD, now=now)
    source.complete(now=now)
    with pytest.raises(IntegrityError):
        async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
            await uow.transfers.add(source)
            journal = SqlAlchemyLedgerTransactionModel(id=uuid4(), transfer_id=source.id, kind='p2p_transfer', currency='USD', posted_at=now)
            uow.session.add(journal)
            await uow.session.flush()
            account = await uow.ledger_accounts.get_by_wallet_id_for_update(UUID(ctx.a))
            uow.session.add(SqlAlchemyLedgerEntryModel(id=uuid4(), ledger_transaction_id=journal.id,
                ledger_account_id=account.id, side='debit', amount_minor=1, currency='USD', created_at=now))
            await uow.commit()
    assert (await top_up(ctx)).status_code == 201
    for stmt in (update(SqlAlchemyIdempotencyModel).values(resource_id=uuid4()), delete(SqlAlchemyIdempotencyModel)):
        with pytest.raises(IntegrityError):
            async with ctx.factory() as session:
                await session.execute(stmt)
                await session.commit()


async def test_empty_filtered_summaries_and_closed_wallet_history(ctx):
    summary = await ctx.client.get('/v1/users/me/balances?currency=JPY', headers=ctx.headers[1])
    assert summary.json()['totals'] == []
    history = await ctx.client.get('/v1/wallets/' + ctx.a + '/transactions', headers=ctx.headers[1])
    assert history.json() == {'items': [], 'next_cursor': None}
    assert (await top_up(ctx, amount='10000')).status_code == 201
    assert (await transfer(ctx, receiver=ctx.own, amount='10000')).status_code == 201
    assert (await ctx.client.post('/v1/wallets/' + ctx.a + '/close', headers=ctx.headers[1])).status_code == 204
    assert (await balance(ctx))['posted_minor'] == '0'
    history = await ctx.client.get('/v1/wallets/' + ctx.a + '/transactions', headers=ctx.headers[1], params={
        'kind': 'p2p_transfer', 'currency': 'USD', 'direction': 'outgoing',
        'posted_from': '2026-11-03T00:00:00Z', 'posted_to': '2026-11-04T00:00:00Z',
    })
    assert len(history.json()['items']) == 1
    for direction, count in (('outgoing', 0), ('incoming', 0), ('internal', 1)):
        response = await ctx.client.get('/v1/transfers', headers=ctx.headers[1], params={
            'direction': direction, 'currency': 'USD', 'status': 'completed',
            'created_from': '2026-11-03T00:00:00Z', 'created_to': '2026-11-04T00:00:00Z',
        })
        assert len(response.json()['items']) == count


async def test_operator_provisioning_grant_revoke_and_inactive_user(ctx, monkeypatch):
    from unittest.mock import AsyncMock
    from backend.bootstrap import sandbox

    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(sandbox, 'create_engine', lambda settings: engine)
    monkeypatch.setattr(sandbox, 'create_session_factory', lambda engine: ctx.factory)
    actor = ctx.users[1]
    await sandbox.configure_operator(actor.id)
    await sandbox.configure_operator(actor.id)  # Repeated grant is idempotent.
    async with ctx.factory() as session:
        assert await session.get(SqlAlchemySandboxOperatorModel, actor.id) is not None
        from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyLedgerAccountModel
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyLedgerAccountModel).where(
            SqlAlchemyLedgerAccountModel.wallet_id.is_(None))) == len(CurrencyEnum)
    await sandbox.configure_operator(actor.id, revoke=True)
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        assert not await uow.sandbox_operator_reader.is_operator(actor.id)
        user = await uow.users.get_by_id_for_update(actor.id)
        user.suspend()
        await uow.users.save(user)
        await uow.commit()
    with pytest.raises(ValueError, match='active'):
        await sandbox.configure_operator(actor.id)
    with pytest.raises(ValueError, match='does not exist'):
        await sandbox.configure_operator(uuid4())
    assert engine.dispose.await_count == 5


async def test_db_preserves_wallet_and_account_identity(ctx):
    from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyWalletModel, SqlAlchemyLedgerAccountModel
    for stmt in (
        update(SqlAlchemyWalletModel).where(SqlAlchemyWalletModel.id == UUID(ctx.a)).values(user_id=ctx.users[3].id),
        update(SqlAlchemyLedgerAccountModel).where(SqlAlchemyLedgerAccountModel.wallet_id == UUID(ctx.a)).values(code='altered'),
    ):
        with pytest.raises(IntegrityError):
            async with ctx.factory() as session:
                await session.execute(stmt)
                await session.commit()


async def test_rate_limited_replay_does_not_repeat_transfer_or_change_balance(ctx):
    ctx.settings.transfer_rate_limit_user_per_minute = 1
    assert (await top_up(ctx)).status_code == 201
    first = await transfer(ctx, key='rate-limited-replay')
    assert first.status_code == 201
    blocked = await transfer(ctx, key='rate-limited-replay')
    assert blocked.status_code == 429 and int(blocked.headers['retry-after']) > 0
    assert (await balance(ctx))['posted_minor'] == '40000'
    # Simulate budget becoming available without creating another intent.
    ctx.settings.transfer_rate_limit_user_per_minute = 2
    replay = await transfer(ctx, key='rate-limited-replay')
    assert replay.status_code == 201 and replay.json() == first.json()
    async with ctx.factory() as session:
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyTransferModel)) == 1
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyLedgerTransactionModel)) == 2
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyIdempotencyModel)) == 2


async def test_unavailable_redis_cannot_create_financial_records(ctx, monkeypatch):
    from unittest.mock import AsyncMock
    from redis.exceptions import ConnectionError
    assert (await top_up(ctx)).status_code == 201
    monkeypatch.setattr(ctx.redis.limiter, '_consume', AsyncMock(side_effect=ConnectionError('private-store-error')))
    response = await transfer(ctx, key='unavailable-store')
    assert response.status_code == 503 and 'private-store-error' not in response.text
    assert (await balance(ctx))['posted_minor'] == '50000'
    async with ctx.factory() as session:
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyTransferModel)) == 0
        assert await session.scalar(select(func.count()).select_from(SqlAlchemyIdempotencyModel)) == 1


async def test_owner_freeze_blocks_new_money_but_keeps_history_balance_and_replays(ctx):
    assert (await top_up(ctx)).status_code == 201
    completed = await transfer(ctx, amount='1000', key='before-freeze')
    assert completed.status_code == 201
    assert (await ctx.client.post(f'/v1/wallets/{ctx.a}/freeze', headers=ctx.headers[1])).status_code == 204
    snapshot = await balance(ctx)
    assert snapshot['posted_minor'] == snapshot['available_minor'] == '49000'
    assert snapshot['spendable_minor'] == '0'
    replay = await transfer(ctx, amount='1000', key='before-freeze')
    assert replay.status_code == 201 and replay.json() == completed.json()
    responses = await asyncio.gather(transfer(ctx, amount='100'),
                                     transfer(ctx, sender=ctx.b, receiver=ctx.a, actor=2, amount='100'),
                                     top_up(ctx, amount='100'))
    for response in responses:
        assert response.status_code == 409 and response.json()['detail']['code'] == 'wallet_not_active'
    after = await balance(ctx)
    assert {key: value for key, value in after.items() if key != 'as_of'} == {
        key: value for key, value in snapshot.items() if key != 'as_of'}
    history = await ctx.client.get(f'/v1/wallets/{ctx.a}/transactions', headers=ctx.headers[1])
    assert history.status_code == 200 and len(history.json()['items']) == 2
    assert (await ctx.client.post(f'/v1/wallets/{ctx.a}/unfreeze', headers=ctx.headers[1])).status_code == 204
    assert (await transfer(ctx, amount='100')).status_code == 201
    assert (await top_up(ctx, amount='100')).status_code == 201
    assert (await balance(ctx))['posted_minor'] == '49000'


@pytest.mark.parametrize('side', ['sender', 'receiver'])
async def test_concurrent_posting_waits_for_freeze_then_checks_locked_status(ctx, monkeypatch, side):
    from backend.domain.wallet.enums import WalletStatusEnum
    from backend.infrastructure.db.sqlalchemy.repository.wallet import SqlAlchemyWalletRepository
    assert (await top_up(ctx)).status_code == 201
    wallet_id, actor = (ctx.a, 1) if side == 'sender' else (ctx.b, 2)
    saved, release = asyncio.Event(), asyncio.Event()
    original_save = SqlAlchemyWalletRepository.save
    async def pause_after_save(self, wallet):
        await original_save(self, wallet)
        if str(wallet.id) == wallet_id and wallet.status == WalletStatusEnum.FROZEN:
            saved.set()
            await asyncio.wait_for(release.wait(), timeout=4)
    monkeypatch.setattr(SqlAlchemyWalletRepository, 'save', pause_after_save)
    freeze_task = asyncio.create_task(ctx.client.post(f'/v1/wallets/{wallet_id}/freeze', headers=ctx.headers[actor]))
    await asyncio.wait_for(saved.wait(), timeout=3)
    transfer_task = asyncio.create_task(transfer(ctx, amount='100'))
    try:
        done, _ = await asyncio.wait({transfer_task}, timeout=0.1)
        assert not done, 'Posting must wait for the uncommitted wallet status change'
    finally:
        release.set()
    frozen, moved = await asyncio.wait_for(asyncio.gather(freeze_task, transfer_task), timeout=4)
    assert frozen.status_code == 204
    assert moved.status_code == 409 and moved.json()['detail']['code'] == 'wallet_not_active'
    assert (await balance(ctx))['posted_minor'] == '50000'
    assert (await balance(ctx, ctx.b, actor=2))['posted_minor'] == '0'

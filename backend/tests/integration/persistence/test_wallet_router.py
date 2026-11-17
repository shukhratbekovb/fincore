from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from backend.domain.ledger_account.enums import AccountStatus, AccountType
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, HashedPassword, Username
from backend.domain.wallet.enums import WalletStatusEnum
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyWalletModel, SqlAlchemyWalletBalanceModel, SqlAlchemyLedgerAccountModel
from backend.infrastructure.security.token_issuer import JWTTokenIssuer
from backend.infrastructure.settings import Settings, get_settings
from backend.main import app
from backend.presentation.api.v1.dependencies.core import get_clock


@pytest.fixture
async def context(session_factory, monkeypatch, now):
    user = User.created_by_admin(Username('alice'), Email('alice@example.com'), HashedPassword('unused-hash'))
    other = User.created_by_admin(Username('otheruser'), Email('other@example.com'), HashedPassword('unused-hash'))
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.users.add(user)
        await uow.users.add(other)
        await uow.commit()
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test', jwt_secret_key='wallet-router-db-test-key-' * 3)
    clock = SimpleNamespace(now=lambda: now)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setitem(app.dependency_overrides, get_clock, lambda: clock)
    monkeypatch.setattr(app.state, 'session_factory', session_factory, raising=False)
    issuer = JWTTokenIssuer(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield SimpleNamespace(client=client, user=user, other=other, factory=session_factory,
                              headers={'Authorization': 'Bearer ' + issuer.encode(user.id)},
                              other_headers={'Authorization': 'Bearer ' + issuer.encode(other.id)})


async def create_wallet(ctx, name='Main', currency='CAD'):
    response = await ctx.client.post('/v1/wallets', json={'name': name, 'currency': currency}, headers=ctx.headers)
    assert response.status_code == 201
    return UUID(response.json()['wallet_id'])


async def test_create_rename_close_and_ownership_over_http_and_postgresql(context):
    ctx = context
    wallet_id = await create_wallet(ctx)
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        wallet = await uow.wallets.get_by_id_for_update(wallet_id)
        balance = await uow.wallet_balances.get_by_wallet_id_for_update(wallet_id)
        account = await uow.ledger_accounts.get_by_wallet_id_for_update(wallet_id)
        assert wallet.user_id == ctx.user.id and wallet.currency == CurrencyEnum.CAD
        assert wallet.name.value == 'Main'
        assert len(wallet.number.value) == 20
        assert balance.posted_minor == 0 and balance.version == 0
        assert account.account_type == AccountType.LIABILITY and account.currency == CurrencyEnum.CAD

    # An authenticated different owner gets the same response as for an absent wallet.
    foreign = await ctx.client.patch('/v1/wallets/' + str(wallet_id), json={'name': 'Stolen'}, headers=ctx.other_headers)
    missing = await ctx.client.patch('/v1/wallets/' + str(uuid4()), json={'name': 'Stolen'}, headers=ctx.other_headers)
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()
    assert (await ctx.client.post('/v1/wallets/' + str(wallet_id) + '/close', headers=ctx.other_headers)).status_code == 404

    response = await ctx.client.patch('/v1/wallets/' + str(wallet_id), json={'name': '  Savings  '}, headers=ctx.headers)
    assert response.status_code == 204 and response.content == b''
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        wallet = await uow.wallets.get_by_id_for_update(wallet_id)
        assert wallet.name.value == 'Savings' and wallet.status == WalletStatusEnum.ACTIVE

    for _ in range(2):
        response = await ctx.client.post('/v1/wallets/' + str(wallet_id) + '/close', headers=ctx.headers)
        assert response.status_code == 204 and response.content == b''
        assert response.headers['cache-control'] == 'no-store'
    response = await ctx.client.patch('/v1/wallets/' + str(wallet_id), json={'name': 'Forbidden'}, headers=ctx.headers)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'wallet_closed'
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        wallet = await uow.wallets.get_by_id_for_update(wallet_id)
        account = await uow.ledger_accounts.get_by_wallet_id_for_update(wallet_id)
        balance = await uow.wallet_balances.get_by_wallet_id_for_update(wallet_id)
        assert wallet.status == WalletStatusEnum.CLOSED and wallet.name.value == 'Savings'
        assert account.status == AccountStatus.CLOSED and balance.posted_minor == 0


async def test_nonzero_balance_returns_409_and_preserves_statuses(context, now):
    ctx = context
    wallet_id = await create_wallet(ctx)
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        balance = await uow.wallet_balances.get_by_wallet_id_for_update(wallet_id)
        balance.credit(100, now=now)
        await uow.wallet_balances.save(balance)
        await uow.commit()
    response = await ctx.client.post('/v1/wallets/' + str(wallet_id) + '/close', headers=ctx.headers)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'wallet_balance_not_zero'
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        assert (await uow.wallets.get_by_id_for_update(wallet_id)).status == WalletStatusEnum.ACTIVE
        assert (await uow.ledger_accounts.get_by_wallet_id_for_update(wallet_id)).status == AccountStatus.ACTIVE
        assert (await uow.wallet_balances.get_by_wallet_id_for_update(wallet_id)).posted_minor == 100


async def test_closure_failure_rolls_back_wallet_and_account_statuses(context, monkeypatch):
    from backend.infrastructure.db.sqlalchemy.repository.ledger_account import SqlAlchemyLedgerAccountRepository
    ctx = context
    wallet_id = await create_wallet(ctx)
    async def fail_save(self, account):
        raise RuntimeError('database write unavailable')
    monkeypatch.setattr(SqlAlchemyLedgerAccountRepository, 'save', fail_save)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        response = await client.post('/v1/wallets/' + str(wallet_id) + '/close', headers=ctx.headers)
    assert response.status_code == 500
    assert 'database write unavailable' not in response.text
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        assert (await uow.wallets.get_by_id_for_update(wallet_id)).status == WalletStatusEnum.ACTIVE
        assert (await uow.ledger_accounts.get_by_wallet_id_for_update(wallet_id)).status == AccountStatus.ACTIVE


async def test_creation_failure_rolls_back_all_three_records(context, monkeypatch):
    from backend.infrastructure.db.sqlalchemy.repository.ledger_account import SqlAlchemyLedgerAccountRepository
    ctx = context
    async def fail_add(self, account):
        raise RuntimeError('ledger insert unavailable')
    monkeypatch.setattr(SqlAlchemyLedgerAccountRepository, 'add', fail_add)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        response = await client.post('/v1/wallets', json={'name': 'Main'}, headers=ctx.headers)
    assert response.status_code == 500
    async with ctx.factory() as session:
        for model in (SqlAlchemyWalletModel, SqlAlchemyWalletBalanceModel, SqlAlchemyLedgerAccountModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_inactive_owner_cannot_rename_or_close(context):
    ctx = context
    wallet_id = await create_wallet(ctx)
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        user = await uow.users.get_by_id_for_update(ctx.user.id)
        user.suspend()
        await uow.users.save(user)
        await uow.commit()
    for method, path, body in [
        ('PATCH', '/v1/wallets/' + str(wallet_id), {'name': 'Other'}),
        ('POST', '/v1/wallets/' + str(wallet_id) + '/close', None),
    ]:
        response = await ctx.client.request(method, path, json=body, headers=ctx.headers)
        assert response.status_code == 403
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        wallet = await uow.wallets.get_by_id_for_update(wallet_id)
        assert wallet.name.value == 'Main' and wallet.status == WalletStatusEnum.ACTIVE


async def test_wallet_reads_join_balances_filter_and_keep_ownership(context, now):
    from sqlalchemy import event
    ctx = context
    assert (await ctx.client.get('/v1/wallets', headers=ctx.headers)).json() == []
    main = await create_wallet(ctx, name='Main', currency='CAD')
    frozen = await create_wallet(ctx, name='Savings', currency='USD')
    closed = await create_wallet(ctx, name='Closed', currency='CAD')
    foreign_response = await ctx.client.post('/v1/wallets', json={'name': 'Foreign'}, headers=ctx.other_headers)
    foreign = UUID(foreign_response.json()['wallet_id'])
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        for wallet_id, amount in ((main, 100), (frozen, 250)):
            balance = await uow.wallet_balances.get_by_wallet_id_for_update(wallet_id)
            balance.credit(amount, now=now)
            await uow.wallet_balances.save(balance)
        wallet = await uow.wallets.get_by_id_for_update(frozen)
        wallet.freeze()
        await uow.wallets.save(wallet)
        await uow.commit()
    assert (await ctx.client.post('/v1/wallets/' + str(closed) + '/close', headers=ctx.headers)).status_code == 204

    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)
    engine = ctx.factory.kw['bind'].sync_engine
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        response = await ctx.client.get('/v1/wallets', params={'sort_by': 'balance:desc', 'user_id': str(ctx.other.id)}, headers=ctx.headers)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert [item['id'] for item in response.json()] == [str(frozen), str(main), str(closed)]
    assert [item['balance_minor'] for item in response.json()] == ['250', '100', '0']
    assert all(item['user_id'] == str(ctx.user.id) for item in response.json())
    # One user SELECT plus one wallet/balance SELECT, regardless of list size.
    assert len(statements) == 2
    assert sum('LEFT OUTER JOIN wallet_balances' in statement for statement in statements) == 1
    assert all('FOR UPDATE' not in statement.upper() for statement in statements)

    for params, expected in [
        ({'currency': 'CAD', 'status': 'active'}, main),
        ({'currency': 'USD', 'status': 'frozen'}, frozen),
        ({'status': 'closed'}, closed),
    ]:
        response = await ctx.client.get('/v1/wallets', params=params, headers=ctx.headers)
        assert response.status_code == 200 and [item['id'] for item in response.json()] == [str(expected)]
    response = await ctx.client.get('/v1/wallets', params={'currency': 'JPY'}, headers=ctx.headers)
    assert response.status_code == 200 and response.json() == []
    response = await ctx.client.get('/v1/wallets/' + str(main), headers=ctx.headers)
    assert response.status_code == 200 and response.json()['balance_minor'] == '100'
    assert response.json()['currency'] == 'CAD'
    response = await ctx.client.get('/v1/wallets/' + str(closed), headers=ctx.headers)
    assert response.status_code == 200 and response.json()['status'] == 'closed'
    foreign_response = await ctx.client.get('/v1/wallets/' + str(foreign), headers=ctx.headers)
    missing_response = await ctx.client.get('/v1/wallets/' + str(uuid4()), headers=ctx.headers)
    assert foreign_response.status_code == missing_response.status_code == 404
    assert foreign_response.json() == missing_response.json()


async def test_wallet_list_sorting_uses_id_when_primary_values_are_equal(context, now):
    from backend.domain.wallet.entities import Wallet
    from backend.domain.wallet.value_objects import WalletName, WalletNumber
    from backend.domain.wallet_balance.entities import WalletBalance
    from backend.domain.ledger_account.entities import LedgerAccount
    ctx = context
    ids = []
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        for index in range(3):
            wallet = Wallet(user_id=ctx.user.id, name=WalletName('Same'),
                            number=WalletNumber(str(10000000000000000000 + index)),
                            currency=CurrencyEnum.CAD, created_at=now, updated_at=now)
            await uow.wallets.add(wallet)
            await uow.wallet_balances.add(WalletBalance.create(wallet_id=wallet.id, now=now))
            await uow.ledger_accounts.add(LedgerAccount.for_wallet(wallet_id=wallet.id, currency=wallet.currency, now=now))
            ids.append(wallet.id)
        await uow.commit()
    for params in ({}, {'sort_by': 'name:asc'}, {'sort_by': 'balance:desc'}):
        response = await ctx.client.get('/v1/wallets', params=params, headers=ctx.headers)
        assert response.status_code == 200
        assert [item['id'] for item in response.json()] == [str(item) for item in sorted(ids)]


async def test_missing_balance_is_error_only_for_its_owner(context):
    from sqlalchemy import delete
    ctx = context
    wallet_id = await create_wallet(ctx)
    async with ctx.factory.begin() as session:
        await session.execute(delete(SqlAlchemyWalletBalanceModel).where(SqlAlchemyWalletBalanceModel.wallet_id == wallet_id))
    for path in ('/v1/wallets', '/v1/wallets/' + str(wallet_id)):
        response = await ctx.client.get(path, headers=ctx.headers)
        assert response.status_code == 500
        assert response.json()['detail']['code'] == 'wallet_accounting_state_error'
    # Ownership is filtered before mapping, so another user cannot observe the broken balance.
    response = await ctx.client.get('/v1/wallets/' + str(wallet_id), headers=ctx.other_headers)
    assert response.status_code == 404 and response.json()['detail']['code'] == 'wallet_not_found'
    response = await ctx.client.get('/v1/wallets', headers=ctx.other_headers)
    assert response.status_code == 200 and response.json() == []


async def test_inactive_user_cannot_read_wallets_with_previously_issued_jwt(context):
    ctx = context
    wallet_id = await create_wallet(ctx)
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        user = await uow.users.get_by_id_for_update(ctx.user.id)
        user.suspend()
        await uow.users.save(user)
        await uow.commit()
    for path in ('/v1/wallets', '/v1/wallets/' + str(wallet_id)):
        response = await ctx.client.get(path, headers=ctx.headers)
        assert response.status_code == 403 and response.json()['detail']['code'] == 'user_inactive'


async def test_freeze_unfreeze_preserve_accounting_and_repeats_do_not_touch_timestamp(context):
    ctx = context
    wallet_id = await create_wallet(ctx)
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        balance = await uow.wallet_balances.get_by_wallet_id_for_update(wallet_id)
        balance.credit(12500, now=balance.updated_at)
        await uow.wallet_balances.save(balance)
        await uow.commit()
    for operation, expected in [('freeze', WalletStatusEnum.FROZEN), ('unfreeze', WalletStatusEnum.ACTIVE)]:
        response = await ctx.client.post(f'/v1/wallets/{wallet_id}/{operation}', headers=ctx.headers)
        assert response.status_code == 204 and response.content == b''
        async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
            wallet = await uow.wallets.get_by_id_for_update(wallet_id)
            updated_at = wallet.updated_at
            assert wallet.status == expected
            assert (await uow.wallet_balances.get_by_wallet_id_for_update(wallet_id)).posted_minor == 12500
            assert (await uow.ledger_accounts.get_by_wallet_id_for_update(wallet_id)).status == AccountStatus.ACTIVE
        response = await ctx.client.post(f'/v1/wallets/{wallet_id}/{operation}', headers=ctx.headers)
        assert response.status_code == 204
        async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
            assert (await uow.wallets.get_by_id_for_update(wallet_id)).updated_at == updated_at


@pytest.mark.parametrize('operation', ['freeze', 'unfreeze'])
async def test_freeze_unfreeze_never_expose_foreign_state_or_reopen_closed_wallet(context, operation):
    ctx = context
    wallet_id = await create_wallet(ctx)
    foreign = await ctx.client.post(f'/v1/wallets/{wallet_id}/{operation}', headers=ctx.other_headers)
    missing = await ctx.client.post(f'/v1/wallets/{uuid4()}/{operation}', headers=ctx.other_headers)
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()
    assert (await ctx.client.post(f'/v1/wallets/{wallet_id}/close', headers=ctx.headers)).status_code == 204
    response = await ctx.client.post(f'/v1/wallets/{wallet_id}/{operation}', headers=ctx.headers)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'wallet_closed'
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        assert (await uow.wallets.get_by_id_for_update(wallet_id)).status == WalletStatusEnum.CLOSED
        assert (await uow.ledger_accounts.get_by_wallet_id_for_update(wallet_id)).status == AccountStatus.CLOSED


@pytest.mark.parametrize('operation', ['freeze', 'unfreeze'])
async def test_freeze_unfreeze_storage_failure_rolls_back_status(context, monkeypatch, operation):
    from backend.infrastructure.db.sqlalchemy.repository.wallet import SqlAlchemyWalletRepository
    ctx = context
    wallet_id = await create_wallet(ctx)
    if operation == 'unfreeze':
        assert (await ctx.client.post(f'/v1/wallets/{wallet_id}/freeze', headers=ctx.headers)).status_code == 204
    previous = WalletStatusEnum.ACTIVE if operation == 'freeze' else WalletStatusEnum.FROZEN
    save = SqlAlchemyWalletRepository.save
    async def fail_after_save(self, wallet):
        await save(self, wallet)
        raise RuntimeError('wallet storage unavailable')
    monkeypatch.setattr(SqlAlchemyWalletRepository, 'save', fail_after_save)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        response = await client.post(f'/v1/wallets/{wallet_id}/{operation}', headers=ctx.headers)
    assert response.status_code == 500 and 'wallet storage unavailable' not in response.text
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        assert (await uow.wallets.get_by_id_for_update(wallet_id)).status == previous
        assert (await uow.ledger_accounts.get_by_wallet_id_for_update(wallet_id)).status == AccountStatus.ACTIVE


async def test_concurrent_freeze_and_close_leave_wallet_and_account_closed(context):
    import asyncio
    ctx = context
    wallet_id = await create_wallet(ctx)
    freeze, close = await asyncio.wait_for(asyncio.gather(
        ctx.client.post(f'/v1/wallets/{wallet_id}/freeze', headers=ctx.headers),
        ctx.client.post(f'/v1/wallets/{wallet_id}/close', headers=ctx.headers),
    ), timeout=4)
    assert freeze.status_code in (204, 409) and close.status_code == 204
    async with SqlAlchemyUnitOfWork(ctx.factory) as uow:
        assert (await uow.wallets.get_by_id_for_update(wallet_id)).status == WalletStatusEnum.CLOSED
        assert (await uow.ledger_accounts.get_by_wallet_id_for_update(wallet_id)).status == AccountStatus.CLOSED

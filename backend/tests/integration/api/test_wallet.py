from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from backend.application.wallet.errors import WalletNumberAlreadyExistsError, WalletAccountingStateError
from backend.application.wallet.dtos.base import WalletDTO
from backend.application.wallet.dtos.filters import WalletSortEnum
from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_account.enums import AccountStatus
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, HashedPassword, Username
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.value_objects import WalletName, WalletNumber
from backend.domain.wallet_balance.entities import WalletBalance
from backend.infrastructure.security.token_issuer import JWTTokenIssuer
from backend.infrastructure.settings import Settings, get_settings
from backend.main import app
from backend.presentation.api.v1.dependencies.core import get_clock, get_uow

SECRET = 'wallet-api-test-secret-' * 3
ROUTES = [('POST', '/v1/wallets', {'name': 'Main'}),
          ('PATCH', '/v1/wallets/{wallet_id}', {'name': 'Savings'}),
          ('POST', '/v1/wallets/{wallet_id}/close', None),
          ('POST', '/v1/wallets/{wallet_id}/freeze', None),
          ('POST', '/v1/wallets/{wallet_id}/unfreeze', None)]


@pytest.fixture
async def context(monkeypatch, now):
    user = User.created_by_admin(Username('alice'), Email('alice@example.com'), HashedPassword('test-hash'))
    wallet = Wallet.create(user.id, WalletName('Main'), WalletNumber('1' * 20), CurrencyEnum.USD)
    balance = WalletBalance.create(wallet_id=wallet.id, now=now)
    account = LedgerAccount.for_wallet(wallet_id=wallet.id, currency=wallet.currency, now=now)
    uow = AsyncMock()
    uow.users.get_by_id.return_value = user
    uow.users.get_by_id_for_update.return_value = user
    uow.wallets.get_by_id_for_update.return_value = wallet
    uow.wallet_balances.get_by_wallet_id_for_update.return_value = balance
    uow.ledger_accounts.get_by_wallet_id_for_update.return_value = account
    dto = WalletDTO(
        id=wallet.id, user_id=user.id, name=wallet.name.value, balance_minor=balance.posted_minor,
        number=wallet.number.value, currency=wallet.currency, status=wallet.status,
        created_at=wallet.created_at, updated_at=wallet.updated_at,
    )
    uow.wallet_reader.get_by_id_for_user.return_value = dto
    uow.wallet_reader.list_by_user_id.return_value = [dto]
    factory = Mock(return_value=uow)
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://localhost/fincore_test', jwt_secret_key=SECRET)
    clock = SimpleNamespace(now=lambda: now)
    monkeypatch.setitem(app.dependency_overrides, get_uow, lambda: factory())
    monkeypatch.setitem(app.dependency_overrides, get_clock, lambda: clock)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    token = JWTTokenIssuer(settings).encode(user.id)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        yield SimpleNamespace(client=client, user=user, wallet=wallet, balance=balance, account=account,
                              uow=uow, factory=factory, headers={'Authorization': 'Bearer ' + token}, token=token)


@pytest.mark.parametrize('currency', [None, *CurrencyEnum])
async def test_create_returns_id_and_initializes_matching_accounting(context, currency):
    ctx = context
    body = {'name': '  Main  '}
    if currency is not None:
        body['currency'] = currency.value
    response = await ctx.client.post('/v1/wallets', json=body, headers=ctx.headers)
    assert response.status_code == 201
    wallet = ctx.uow.wallets.add.call_args.args[0]
    balance = ctx.uow.wallet_balances.add.call_args.args[0]
    account = ctx.uow.ledger_accounts.add.call_args.args[0]
    assert response.json() == {'wallet_id': str(wallet.id)}
    assert wallet.user_id == ctx.user.id
    assert wallet.name.value == 'Main'
    assert wallet.currency == (currency or CurrencyEnum.USD)
    assert len(wallet.number.value) == 20 and wallet.number.value.isascii() and wallet.number.value.isdigit()
    assert balance.wallet_id == account.wallet_id == wallet.id and balance.posted_minor == 0
    assert account.currency == wallet.currency
    assert response.headers['cache-control'] == 'no-store'
    ctx.uow.commit.assert_awaited_once()


async def test_wallet_name_is_trimmed_before_length_validation(context):
    response = await context.client.post('/v1/wallets', json={'name': '  ' + 'x' * 64 + '  '}, headers=context.headers)
    assert response.status_code == 201
    assert context.uow.wallets.add.call_args.args[0].name.value == 'x' * 64


@pytest.mark.parametrize('frozen', [False, True])
async def test_rename_updates_only_name_and_returns_empty_204(context, frozen):
    ctx = context
    if frozen:
        ctx.wallet.freeze()
    number, currency = ctx.wallet.number, ctx.wallet.currency
    response = await ctx.client.patch('/v1/wallets/' + str(ctx.wallet.id), json={'name': '  Savings  '}, headers=ctx.headers)
    assert response.status_code == 204 and response.content == b''
    assert ctx.wallet.name.value == 'Savings'
    assert ctx.wallet.number == number and ctx.wallet.currency == currency
    ctx.uow.wallets.save.assert_awaited_once_with(ctx.wallet)
    ctx.uow.commit.assert_awaited_once()


async def test_close_is_repeatable_and_closes_wallet_and_account(context):
    ctx = context
    for _ in range(2):
        response = await ctx.client.post('/v1/wallets/' + str(ctx.wallet.id) + '/close', headers=ctx.headers)
        assert response.status_code == 204 and response.content == b''
    assert ctx.wallet.status == WalletStatusEnum.CLOSED
    assert ctx.account.status == AccountStatus.CLOSED
    assert ctx.balance.posted_minor == 0


@pytest.mark.parametrize('method,path,body', ROUTES)
async def test_query_parameters_cannot_change_the_owner(context, method, path, body):
    ctx = context
    response = await ctx.client.request(method, path.format(wallet_id=ctx.wallet.id), json=body,
                                       params={'user_id': str(uuid4())}, headers=ctx.headers)
    assert response.status_code == (201 if path == '/v1/wallets' else 204)
    ctx.uow.users.get_by_id.assert_awaited_once_with(ctx.user.id)
    assert ctx.wallet.user_id == ctx.user.id
    if path == '/v1/wallets':
        assert ctx.uow.wallets.add.call_args.args[0].user_id == ctx.user.id


@pytest.mark.parametrize('method,path,body', ROUTES)
@pytest.mark.parametrize('problem', ['missing', 'invalid', 'expired'])
async def test_jwt_must_be_valid_before_database_access(context, method, path, body, problem):
    ctx = context
    headers, code = {}, 'http_error'
    if problem == 'invalid':
        headers = {'Authorization': 'Bearer ' + jwt.encode(jwt.get_unverified_claims(ctx.token), 'another-test-secret-' * 3, algorithm='HS256')}
        code = 'invalid_access_token'
    elif problem == 'expired':
        claims = jwt.get_unverified_claims(ctx.token)
        stamp = int(datetime.now(timezone.utc).timestamp())
        claims.update(iat=stamp - 120, nbf=stamp - 120, exp=stamp - 60)
        headers = {'Authorization': 'Bearer ' + jwt.encode(claims, SECRET, algorithm='HS256')}
        code = 'access_token_expired'
    response = await ctx.client.request(method, path.format(wallet_id=ctx.wallet.id), json=body, headers=headers)
    assert response.status_code == 401 and response.json()['detail']['code'] == code
    ctx.factory.assert_not_called()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('method,path,body', ROUTES)
@pytest.mark.parametrize('problem', ['missing', 'inactive'])
async def test_user_must_exist_and_be_active_before_mutations(context, method, path, body, problem):
    ctx = context
    if problem == 'missing':
        ctx.uow.users.get_by_id.return_value = None
    else:
        ctx.user.suspend()
    response = await ctx.client.request(method, path.format(wallet_id=ctx.wallet.id), json=body, headers=ctx.headers)
    assert response.status_code == (404 if problem == 'missing' else 403)
    ctx.uow.wallets.add.assert_not_awaited()
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('operation', ['rename', 'close'])
@pytest.mark.parametrize('problem', ['missing', 'foreign'])
async def test_missing_and_foreign_wallets_return_same_404(context, operation, problem):
    ctx = context
    if problem == 'missing':
        ctx.uow.wallets.get_by_id_for_update.return_value = None
    else:
        ctx.wallet.user_id = uuid4()
    path = '/v1/wallets/' + str(ctx.wallet.id)
    response = (await ctx.client.patch(path, json={'name': 'Other'}, headers=ctx.headers) if operation == 'rename'
                else await ctx.client.post(path + '/close', headers=ctx.headers))
    assert response.status_code == 404
    assert response.json()['detail'] == {'code': 'wallet_not_found', 'message': 'Wallet not found', 'errors': []}
    ctx.uow.wallets.save.assert_not_awaited()
    ctx.uow.ledger_accounts.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('method,path,body,field', [
    ('POST', '/v1/wallets', {}, 'name'), ('POST', '/v1/wallets', {'name': ''}, 'name'),
    ('POST', '/v1/wallets', {'name': '  '}, 'name'), ('POST', '/v1/wallets', {'name': 'x' * 65}, 'name'),
    ('POST', '/v1/wallets', {'name': 123}, 'name'), ('POST', '/v1/wallets', {'name': 'Main', 'currency': 'BTC'}, 'currency'),
    ('POST', '/v1/wallets', {'name': 'Main', 'user_id': 'forged'}, 'user_id'),
    ('POST', '/v1/wallets', {'name': 'Main', 'balance': 100}, 'balance'),
    ('PATCH', '/v1/wallets/{wallet_id}', {'name': '  '}, 'name'),
    ('PATCH', '/v1/wallets/{wallet_id}', {'name': 'Other', 'currency': 'CAD'}, 'currency'),
])
async def test_invalid_and_server_controlled_fields_are_rejected(context, method, path, body, field):
    ctx = context
    response = await ctx.client.request(method, path.format(wallet_id=ctx.wallet.id), json=body, headers=ctx.headers)
    assert response.status_code == 422
    assert response.json()['detail']['errors'][0]['loc'] == ['body', field]
    ctx.uow.wallets.add.assert_not_awaited()
    ctx.uow.wallets.get_by_id_for_update.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('method,path,body', ROUTES[1:])
async def test_invalid_path_uuid_is_422_without_mutation(context, method, path, body):
    response = await context.client.request(method, path.format(wallet_id='not-a-uuid'), json=body, headers=context.headers)
    assert response.status_code == 422
    assert response.json()['detail']['errors'][0]['loc'] == ['path', 'wallet_id']
    context.uow.wallets.get_by_id_for_update.assert_not_awaited()
    context.uow.commit.assert_not_awaited()


async def test_rename_closed_wallet_returns_conflict(context):
    ctx = context
    ctx.wallet.close()
    response = await ctx.client.patch('/v1/wallets/' + str(ctx.wallet.id), json={'name': 'Other'}, headers=ctx.headers)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'wallet_closed'
    assert ctx.wallet.name.value == 'Main'
    ctx.uow.commit.assert_not_awaited()


async def test_nonzero_balance_prevents_closure(context, now):
    ctx = context
    ctx.balance.credit(1, now=now)
    response = await ctx.client.post('/v1/wallets/' + str(ctx.wallet.id) + '/close', headers=ctx.headers)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'wallet_balance_not_zero'
    assert ctx.wallet.status == WalletStatusEnum.ACTIVE and ctx.account.status == AccountStatus.ACTIVE
    ctx.uow.commit.assert_not_awaited()


async def test_inconsistent_accounting_has_controlled_server_error(context):
    ctx = context
    ctx.uow.wallet_balances.get_by_wallet_id_for_update.return_value = None
    response = await ctx.client.post('/v1/wallets/' + str(ctx.wallet.id) + '/close', headers=ctx.headers)
    assert response.status_code == 500 and response.json()['detail']['code'] == 'wallet_accounting_state_error'
    assert str(ctx.wallet.id) not in response.text
    ctx.uow.commit.assert_not_awaited()


async def test_exhausted_number_collisions_return_service_unavailable(context):
    ctx = context
    ctx.uow.wallets.add.side_effect = WalletNumberAlreadyExistsError()
    response = await ctx.client.post('/v1/wallets', json={'name': 'Main'}, headers=ctx.headers)
    assert response.status_code == 503 and response.json()['detail']['code'] == 'wallet_number_unavailable'
    assert ctx.uow.wallets.add.await_count == 3
    ctx.uow.commit.assert_not_awaited()


async def test_wallet_history_uses_the_prepared_query(context):
    context.uow.transaction_history_reader.list_by_wallet_id_for_user.return_value = []
    response = await context.client.get('/v1/wallets/' + str(context.wallet.id) + '/transactions', headers=context.headers)
    assert response.status_code == 200
    assert response.json() == {'items': [], 'next_cursor': None}


async def test_wallet_responses_are_not_cached_behind_proxy_prefix(context):
    async with AsyncClient(transport=ASGITransport(app=app, root_path='/gateway'), base_url='http://test') as client:
        response = await client.post('/gateway/v1/wallets', json={'name': 'Main'}, headers=context.headers)
    assert response.status_code == 201 and response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('single', [False, True])
async def test_get_wallets_returns_safe_dto_and_never_writes(context, single):
    ctx = context
    path = '/v1/wallets' + ('/' + str(ctx.wallet.id) if single else '')
    response = await ctx.client.get(path, headers=ctx.headers, params={'user_id': str(uuid4())})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    data = response.json() if single else response.json()[0]
    assert set(data) == {'id', 'user_id', 'name', 'balance_minor', 'number', 'currency', 'status', 'created_at', 'updated_at'}
    assert data['id'] == str(ctx.wallet.id) and data['user_id'] == str(ctx.user.id)
    assert data['name'] == 'Main' and data['balance_minor'] == '0'
    assert data['currency'] == 'USD' and data['status'] == 'active'
    ctx.uow.users.get_by_id.assert_awaited_once_with(ctx.user.id)
    ctx.uow.users.get_by_id_for_update.assert_not_awaited()
    if single:
        ctx.uow.wallet_reader.get_by_id_for_user.assert_awaited_once_with(ctx.wallet.id, user_id=ctx.user.id)
    else:
        args = ctx.uow.wallet_reader.list_by_user_id.call_args.kwargs
        assert args['user_id'] == ctx.user.id and args['filters'].sort_by == WalletSortEnum.created_at_asc
    ctx.uow.commit.assert_not_awaited()
    ctx.uow.wallets.save.assert_not_awaited()


async def test_wallet_list_without_matches_returns_empty_array(context):
    ctx = context
    ctx.uow.wallet_reader.list_by_user_id.return_value = []
    response = await ctx.client.get('/v1/wallets', headers=ctx.headers)
    assert response.status_code == 200 and response.json() == []


@pytest.mark.parametrize('sort_by', list(WalletSortEnum))
async def test_wallet_filters_are_typed_and_passed_to_reader(context, sort_by):
    ctx = context
    response = await ctx.client.get('/v1/wallets', headers=ctx.headers,
        params={'currency': 'CAD', 'status': 'frozen', 'sort_by': sort_by.value})
    assert response.status_code == 200
    filters = ctx.uow.wallet_reader.list_by_user_id.call_args.kwargs['filters']
    assert filters.currency is CurrencyEnum.CAD
    assert filters.status is WalletStatusEnum.FROZEN
    assert filters.sort_by is sort_by


@pytest.mark.parametrize('parameter,value', [('currency', 'BTC'), ('status', 'unknown'), ('sort_by', 'name;DROP TABLE wallets')])
async def test_invalid_wallet_filters_are_422_before_reader(context, parameter, value):
    ctx = context
    response = await ctx.client.get('/v1/wallets', params={parameter: value}, headers=ctx.headers)
    assert response.status_code == 422
    assert response.json()['detail']['errors'][0]['loc'] == ['query', parameter]
    assert value not in response.text
    ctx.uow.wallet_reader.list_by_user_id.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('single', [False, True])
@pytest.mark.parametrize('problem', ['missing', 'invalid', 'expired'])
async def test_wallet_reads_require_valid_jwt_before_database_access(context, single, problem):
    ctx = context
    headers, code = {}, 'http_error'
    if problem == 'invalid':
        headers = {'Authorization': 'Bearer ' + jwt.encode(jwt.get_unverified_claims(ctx.token), 'wrong-wallet-read-key-' * 3, algorithm='HS256')}
        code = 'invalid_access_token'
    elif problem == 'expired':
        claims = jwt.get_unverified_claims(ctx.token)
        stamp = int(datetime.now(timezone.utc).timestamp())
        claims.update(iat=stamp - 120, nbf=stamp - 120, exp=stamp - 60)
        headers = {'Authorization': 'Bearer ' + jwt.encode(claims, SECRET, algorithm='HS256')}
        code = 'access_token_expired'
    response = await ctx.client.get('/v1/wallets' + ('/' + str(ctx.wallet.id) if single else ''), headers=headers)
    assert response.status_code == 401 and response.json()['detail']['code'] == code
    ctx.factory.assert_not_called()


@pytest.mark.parametrize('single', [False, True])
@pytest.mark.parametrize('problem', ['missing', 'inactive'])
async def test_wallet_reads_reject_missing_and_inactive_user(context, single, problem):
    ctx = context
    if problem == 'missing':
        ctx.uow.users.get_by_id.return_value = None
    else:
        ctx.user.suspend()
    response = await ctx.client.get('/v1/wallets' + ('/' + str(ctx.wallet.id) if single else ''), headers=ctx.headers)
    assert response.status_code == (404 if problem == 'missing' else 403)
    ctx.uow.wallet_reader.get_by_id_for_user.assert_not_awaited()
    ctx.uow.wallet_reader.list_by_user_id.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()


@pytest.mark.parametrize('problem', ['missing', 'foreign'])
async def test_foreign_and_missing_wallet_reads_have_same_404(context, problem):
    from dataclasses import replace
    ctx = context
    reader = ctx.uow.wallet_reader
    reader.get_by_id_for_user.return_value = (None if problem == 'missing'
        else replace(reader.get_by_id_for_user.return_value, user_id=uuid4()))
    response = await ctx.client.get('/v1/wallets/' + str(ctx.wallet.id), headers=ctx.headers)
    assert response.status_code == 404
    assert response.json()['detail'] == {'code': 'wallet_not_found', 'message': 'Wallet not found', 'errors': []}


@pytest.mark.parametrize('single', [False, True])
async def test_missing_balance_is_reported_as_controlled_500(context, single):
    ctx = context
    method = ctx.uow.wallet_reader.get_by_id_for_user if single else ctx.uow.wallet_reader.list_by_user_id
    method.side_effect = WalletAccountingStateError()
    response = await ctx.client.get('/v1/wallets' + ('/' + str(ctx.wallet.id) if single else ''), headers=ctx.headers)
    assert response.status_code == 500 and response.json()['detail']['code'] == 'wallet_accounting_state_error'
    ctx.uow.commit.assert_not_awaited()


async def test_get_wallet_rejects_invalid_uuid(context):
    response = await context.client.get('/v1/wallets/not-a-uuid', headers=context.headers)
    assert response.status_code == 422
    assert response.json()['detail']['errors'][0]['loc'] == ['path', 'wallet_id']
    context.uow.wallet_reader.get_by_id_for_user.assert_not_awaited()


async def test_wallet_number_leading_zeroes_and_large_minor_balance_survive_serialization(context):
    from dataclasses import replace
    ctx = context
    ctx.uow.wallet_reader.get_by_id_for_user.return_value = replace(
        ctx.uow.wallet_reader.get_by_id_for_user.return_value,
        number='00001234567890123456', balance_minor=2 ** 63 - 1,
    )
    response = await ctx.client.get('/v1/wallets/' + str(ctx.wallet.id), headers=ctx.headers)
    assert response.status_code == 200
    assert response.json()['number'] == '00001234567890123456'
    assert response.json()['balance_minor'] == str(2 ** 63 - 1)


@pytest.mark.parametrize('operation', ['freeze', 'unfreeze'])
async def test_freeze_unfreeze_are_repeatable_owner_operations_with_no_money_changes(context, operation):
    ctx = context
    if operation == 'unfreeze':
        ctx.wallet.freeze()
    before_balance = vars(ctx.balance).copy()
    before_account = vars(ctx.account).copy()
    path = f'/v1/wallets/{ctx.wallet.id}/{operation}'
    for _ in range(2):
        response = await ctx.client.post(path, headers=ctx.headers)
        assert response.status_code == 204 and response.content == b''
        assert response.headers['cache-control'] == 'no-store'
    assert ctx.wallet.status == (WalletStatusEnum.FROZEN if operation == 'freeze' else WalletStatusEnum.ACTIVE)
    assert vars(ctx.balance) == before_balance and vars(ctx.account) == before_account
    ctx.uow.wallets.save.assert_awaited_once()
    ctx.uow.commit.assert_awaited_once()


@pytest.mark.parametrize('operation', ['freeze', 'unfreeze'])
@pytest.mark.parametrize('problem', ['foreign', 'missing', 'closed', 'accounting'])
async def test_freeze_unfreeze_error_contract(context, operation, problem):
    ctx = context
    expected = {'foreign': (404, 'wallet_not_found'), 'missing': (404, 'wallet_not_found'),
                'closed': (409, 'wallet_closed'), 'accounting': (500, 'wallet_accounting_state_error')}
    if problem == 'foreign':
        ctx.wallet.user_id = uuid4()
    elif problem == 'missing':
        ctx.uow.wallets.get_by_id_for_update.return_value = None
    elif problem == 'closed':
        ctx.wallet.close()
    else:
        ctx.account.close()
    response = await ctx.client.post(f'/v1/wallets/{ctx.wallet.id}/{operation}', headers=ctx.headers)
    status_code, code = expected[problem]
    assert response.status_code == status_code and response.json()['detail']['code'] == code
    ctx.uow.wallets.save.assert_not_awaited()
    ctx.uow.commit.assert_not_awaited()

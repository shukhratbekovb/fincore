from copy import deepcopy
from importlib.resources import files
import json

import pytest
from fastapi.openapi.models import OpenAPI
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter

from backend.main import app
from backend.presentation.api.documentation.openapi import LocalizedOpenAPI, OPERATIONS
from backend.presentation.api.v1.schemas.auth import (
    ConfirmUserSchema, LoginUserSchema, LogoutUserSchema, RefreshSessionSchema,
    RegisterUserResponse, RegisterUserSchema, TokenResponse,
    ChangePasswordSchema, RequestPasswordResetSchema, ConfirmPasswordResetSchema,
    PasswordResetRequestedResponse, PasswordResetResponse,
    ResendRegistrationConfirmationSchema, RegistrationConfirmationRequestedResponse,
)
from backend.presentation.api.v1.schemas.errors import ErrorResponse
from backend.presentation.api.v1.schemas.user import UserResponse, SessionResponse
from backend.presentation.api.v1.schemas.wallet import CreateWalletSchema, RenameWalletSchema, CreateWalletResponse, WalletResponse
from backend.presentation.api.v1.schemas.finance import (
    BalanceSummaryResponse, PageResponse, TransactionResponse, WalletTransactionResponse, WalletBalanceResponse,
    CreateTransferSchema, CreateSandboxTopUpSchema, CreateTransferResponse, CreateSandboxTopUpResponse, TransferResponse,
)


@pytest.fixture
async def docs_client():
    # Docs do not need the database, secrets, use-case construction or lifespan.
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield client


@pytest.mark.parametrize('locale,summary', [('ru', 'Войти и создать сессию'), ('en', 'Sign in and create a session')])
async def test_localized_schema_is_valid_complete_and_has_examples(docs_client, locale, summary):
    response = await docs_client.get(f'/openapi/{locale}.json')
    assert response.status_code == 200
    assert response.headers['content-language'] == locale
    schema = response.json()
    OpenAPI.model_validate(schema)
    assert schema['info']['x-language'] == locale
    assert schema['paths']['/v1/auth/login']['post']['summary'] == summary
    assert len(schema['info']['description']) > 2000
    assert set(schema['paths']) == {path for path, method in OPERATIONS}
    for path, method in OPERATIONS:
        operation = schema['paths'][path][method]
        assert len(operation['description']) > 300
        for status, result in operation['responses'].items():
            assert result['description']
            if status == '204':
                assert 'content' not in result
            else:
                content = result['content']['application/json']
                assert 'example' in content or 'examples' in content
    for model in schema['components']['schemas'].values():
        assert model['description']
        for field in model.get('properties', {}).values():
            assert field['description']


def contract_without_text(value):
    if isinstance(value, dict):
        return {key: contract_without_text(item) for key, item in value.items()
                if key not in {'title', 'summary', 'description', 'x-displayName', 'x-language'}}
    if isinstance(value, list):
        return [contract_without_text(item) for item in value]
    return value


async def test_languages_preserve_same_api_contract_and_do_not_mutate_base(docs_client):
    app.openapi()
    base_before = deepcopy(app.openapi_schema)
    ru = (await docs_client.get('/openapi/ru.json')).json()
    en = (await docs_client.get('/openapi/en.json')).json()
    assert contract_without_text(ru) == contract_without_text(en)
    assert ru['paths']['/v1/auth/login']['post']['operationId'] == en['paths']['/v1/auth/login']['post']['operationId']
    assert ru['components']['schemas']['LoginUserSchema']['title'] != en['components']['schemas']['LoginUserSchema']['title']
    assert (await docs_client.get('/openapi/ru.json')).json() == ru
    assert app.openapi_schema == base_before
    assert (await docs_client.get('/openapi.json')).json() == en


def test_schema_copies_do_not_share_nested_examples():
    # Generate from a separate captured base to avoid changing the app's cached schemas.
    from fastapi import FastAPI
    from backend.presentation.api.v1.routers import v1_router
    from backend.presentation.api.health import router as health_router
    isolated = FastAPI()
    isolated.include_router(health_router)
    isolated.include_router(v1_router)
    documentation = LocalizedOpenAPI(isolated)
    ru = documentation.schema('ru')
    en = documentation.schema('en')
    ru['paths']['/v1/auth/login']['post']['requestBody']['content']['application/json']['example']['username'] = 'changed'
    assert en['paths']['/v1/auth/login']['post']['requestBody']['content']['application/json']['example']['username'] == 'alice'
    assert isolated.openapi_schema['paths']['/v1/auth/login']['post'].get('description') != ru['paths']['/v1/auth/login']['post']['description']
    assert documentation.schema('en') is en
    isolated.get('/new-endpoint')(lambda: {'status': 'new'})
    assert '/new-endpoint' in documentation.schema('en')['paths']
    assert '/new-endpoint' not in en['paths']


@pytest.mark.parametrize('locale', ['ru', 'en'])
async def test_documented_examples_match_models(docs_client, locale):
    schema = (await docs_client.get(f'/openapi/{locale}.json')).json()
    for operation, model in [
        ('register', RegisterUserSchema), ('confirm', ConfirmUserSchema),
        ('login', LoginUserSchema), ('refresh', RefreshSessionSchema), ('logout', LogoutUserSchema),
        ('change-password', ChangePasswordSchema), ('password-reset/request', RequestPasswordResetSchema),
        ('password-reset/confirm', ConfirmPasswordResetSchema),
        ('confirm/resend', ResendRegistrationConfirmationSchema),
    ]:
        endpoint = schema['paths']['/v1/auth/' + operation]['post']
        model.model_validate(endpoint['requestBody']['content']['application/json']['example'])
        for status, response in endpoint['responses'].items():
            if status == '204':
                continue
            content = response['content']['application/json']
            if int(status) >= 400:
                for example in content['examples'].values():
                    ErrorResponse.model_validate(example['value'])
            else:
                response_model = {
                    'register': RegisterUserResponse,
                    'password-reset/request': PasswordResetRequestedResponse,
                    'password-reset/confirm': PasswordResetResponse,
                    'confirm/resend': RegistrationConfirmationRequestedResponse,
                }.get(operation, TokenResponse)
                response_model.model_validate(content['example'])


@pytest.mark.parametrize('locale', ['ru', 'en'])
async def test_resend_confirmation_documentation_is_public_generic_and_rate_limited(docs_client, locale):
    schema = (await docs_client.get(f'/openapi/{locale}.json')).json()
    operation = schema['paths']['/v1/auth/confirm/resend']['post']
    assert not operation.get('security')
    assert operation['tags'] == ['auth']
    body = operation['requestBody']['content']['application/json']
    assert body['schema'] == {'$ref': '#/components/schemas/ResendRegistrationConfirmationSchema'}
    assert body['example'] == {'email': 'alice@example.com'}
    request_schema = schema['components']['schemas']['ResendRegistrationConfirmationSchema']
    assert request_schema['required'] == ['email']
    assert request_schema['additionalProperties'] is False
    assert set(request_schema['properties']) == {'email'}
    responses = operation['responses']
    assert set(responses) == {'202', '400', '422', '429', '503'}
    accepted = responses['202']['content']['application/json']
    assert accepted['schema'] == {'$ref': '#/components/schemas/RegistrationConfirmationRequestedResponse'}
    assert accepted['example'] == {
        'message': 'If the account is awaiting confirmation, a new confirmation email will be sent.',
    }
    assert responses['429']['headers']['Retry-After']['schema']['type'] == 'integer'
    invalid = responses['422']['content']['application/json']['examples']['request_validation_error']['value']
    assert invalid['detail']['errors'][0]['loc'] == ['body', 'email']


@pytest.mark.parametrize('locale', ['ru', 'en'])
async def test_user_documentation_examples_and_bearer_security(docs_client, locale):
    schema = (await docs_client.get(f'/openapi/{locale}.json')).json()
    for path, method in OPERATIONS:
        if not path.startswith('/v1/users/'):
            continue
        operation = schema['paths'][path][method]
        assert operation['tags'] == ['users']
        assert operation['security'] == [{'HTTPBearer': []}]
        assert 'requestBody' not in operation
        for status, response in operation['responses'].items():
            if status == '204':
                assert 'content' not in response
                continue
            content = response['content']['application/json']
            if int(status) >= 400:
                for example in content['examples'].values():
                    ErrorResponse.model_validate(example['value'])
            else:
                model = (BalanceSummaryResponse if path.endswith('/balances') else
                         PageResponse[TransactionResponse] if path.endswith('/transactions') else
                         UserResponse if path.endswith('/me') else list[SessionResponse])
                TypeAdapter(model).validate_python(content['example'])


@pytest.mark.parametrize('locale', ['ru', 'en'])
async def test_wallet_documentation_examples_security_and_path_parameters(docs_client, locale):
    schema = (await docs_client.get(f'/openapi/{locale}.json')).json()
    for path, method in OPERATIONS:
        if not path.startswith('/v1/wallets'):
            continue
        operation = schema['paths'][path][method]
        assert operation['tags'] == ['wallet']
        assert operation['security'] == [{'HTTPBearer': []}]
        if method == 'patch' or (method == 'post' and path == '/v1/wallets'):
            model = RenameWalletSchema if method == 'patch' else CreateWalletSchema
            model.model_validate(operation['requestBody']['content']['application/json']['example'])
        else:
            assert 'requestBody' not in operation
        for parameter in operation.get('parameters', []):
            if parameter['in'] == 'path':
                assert parameter['name'] == 'wallet_id'
            else:
                assert parameter['in'] == 'query' and parameter['name'] in {
                    'currency', 'status', 'sort_by', 'kind', 'direction', 'posted_from', 'posted_to', 'limit', 'cursor',
                }
            assert parameter['description']
        for status, response in operation['responses'].items():
            if status == '204':
                assert 'content' not in response
                continue
            content = response['content']['application/json']
            if int(status) >= 400:
                for example in content['examples'].values():
                    ErrorResponse.model_validate(example['value'])
            else:
                model = (WalletBalanceResponse if path.endswith('/balance') else
                         PageResponse[WalletTransactionResponse] if path.endswith('/transactions') else
                         (list[WalletResponse] if path == '/v1/wallets' else WalletResponse) if method == 'get' else CreateWalletResponse)
                TypeAdapter(model).validate_python(content['example'])


@pytest.mark.parametrize('locale', ['ru', 'en'])
async def test_financial_documentation_examples_and_idempotency_header(docs_client, locale):
    schema = (await docs_client.get(f'/openapi/{locale}.json')).json()
    models = {
        ('/v1/transfers', 'post'): (CreateTransferSchema, CreateTransferResponse),
        ('/v1/transfers', 'get'): (None, PageResponse[TransferResponse]),
        ('/v1/transfers/{transfer_id}', 'get'): (None, TransferResponse),
        ('/v1/sandbox/top-ups', 'post'): (CreateSandboxTopUpSchema, CreateSandboxTopUpResponse),
    }
    for (path, method), (request_model, response_model) in models.items():
        operation = schema['paths'][path][method]
        assert operation['security'] == [{'HTTPBearer': []}]
        assert operation['tags'] == ['sandbox' if path.startswith('/v1/sandbox') else 'transfers']
        if request_model is not None:
            request_model.model_validate(operation['requestBody']['content']['application/json']['example'])
            key = next(param for param in operation['parameters'] if param['name'] == 'Idempotency-Key')
            assert key['required'] and key['in'] == 'header'
        for status, response in operation['responses'].items():
            content = response['content']['application/json']
            if int(status) >= 400:
                for example in content['examples'].values():
                    ErrorResponse.model_validate(example['value'])
            else:
                TypeAdapter(response_model).validate_python(content['example'])


@pytest.mark.parametrize('locale,other,label', [('ru', 'en', 'Язык документации'), ('en', 'ru', 'Documentation language')])
async def test_redoc_links_correct_schema_and_language(docs_client, locale, other, label):
    response = await docs_client.get(f'/redoc/{locale}')
    assert response.status_code == 200
    assert response.headers['content-language'] == locale
    assert f'<html lang="{locale}">' in response.text
    assert f'spec-url="/openapi/{locale}.json"' in response.text
    assert f'href="/redoc/{other}"' in response.text
    assert 'aria-current="page"' in response.text
    assert label in response.text
    assert 'redoc.standalone.js' in response.text


async def test_default_redoc_redirects_to_russian_and_swagger_stays_available(docs_client):
    response = await docs_client.get('/redoc')
    assert response.status_code == 307
    assert response.headers['location'] == '/redoc/ru'
    assert (await docs_client.get('/docs')).status_code == 200


@pytest.mark.parametrize('path', ['/redoc/fr', '/openapi/fr.json'])
async def test_unsupported_language_returns_validation_error(docs_client, path):
    response = await docs_client.get(path)
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'request_validation_error'


async def test_docs_work_under_proxy_path_prefix():
    async with AsyncClient(
        transport=ASGITransport(app=app, root_path='/gateway'), base_url='http://test',
    ) as client:
        response = await client.get('/redoc/en')
        assert 'spec-url="/gateway/openapi/en.json"' in response.text
        assert 'href="/gateway/redoc/ru"' in response.text
        response = await client.get('/redoc')
        assert response.headers['location'] == '/gateway/redoc/ru'
        schema = (await client.get('/openapi/en.json')).json()
        assert schema['servers'][0]['url'] == '/gateway'
        assert sum(server['url'] == '/gateway' for server in schema['servers']) == 1
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        schema = (await client.get('/openapi/en.json')).json()
        assert all(server['url'] != '/gateway' for server in schema.get('servers', []))


def test_translation_catalogs_cover_the_same_operations_models_and_fields():
    directory = files('backend.presentation.api.documentation').joinpath('content')
    ru = json.loads(directory.joinpath('ru', 'metadata.json').read_text(encoding='utf-8'))
    en = json.loads(directory.joinpath('en', 'metadata.json').read_text(encoding='utf-8'))
    assert ru['operations'].keys() == en['operations'].keys() == set(OPERATIONS.values())
    assert ru['schemas'].keys() == en['schemas'].keys()
    for name, model in ru['schemas'].items():
        assert model['fields'].keys() == en['schemas'][name]['fields'].keys()

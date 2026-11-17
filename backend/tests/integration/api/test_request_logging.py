import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient

from backend.infrastructure.logging import request_id_context
from backend.presentation.api.request_logging import RequestLoggingMiddleware


def request_records(caplog):
    return [record for record in caplog.records if record.name == 'backend.http']


@pytest.mark.parametrize('root_path', ['', '/gateway'])
@pytest.mark.parametrize('method,status_code', [('GET', 200), ('POST', 405)])
async def test_nested_routers_log_full_static_template_without_request_values(caplog, root_path, method, status_code):
    caplog.set_level(logging.INFO, logger='backend.http')
    application = FastAPI(root_path=root_path)
    application.add_middleware(RequestLoggingMiddleware)
    wallets = APIRouter(prefix='/wallets')

    @wallets.get('/{wallet_id}')
    async def endpoint(wallet_id: str):
        return {'ok': True}

    v1 = APIRouter(prefix='/v1')
    v1.include_router(wallets)
    application.include_router(v1)
    async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test') as client:
        response = await client.request(method, root_path + '/v1/wallets/private-wallet?token=private-token')
    assert response.status_code == status_code
    records = request_records(caplog)
    assert len(records) == 1
    assert records[0].route == '/v1/wallets/{wallet_id}'
    assert records[0].status_code == status_code
    assert 'private-wallet' not in caplog.text and 'private-token' not in caplog.text


async def test_concurrent_requests_have_distinct_ids_context_isolation_and_outer_context_restored(caplog):
    caplog.set_level(logging.INFO, logger='backend.http')
    application = FastAPI()
    application.add_middleware(RequestLoggingMiddleware)
    both_started = asyncio.Event()
    observed = []
    @application.get('/wallets/{wallet_id}')
    async def endpoint(wallet_id: str, request: Request):
        observed.append(request_id_context.get())
        if len(observed) == 2:
            both_started.set()
        await both_started.wait()
        assert request_id_context.get() == request.state.request_id
        return {'request_id': request.state.request_id}
    token = request_id_context.set('outer-context')
    try:
        async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test') as client:
            responses = await asyncio.wait_for(asyncio.gather(
                client.get('/wallets/sensitive-wallet-one?token=query-secret', headers={'X-Request-ID': 'forged-id'}),
                client.get('/wallets/sensitive-wallet-two?token=query-secret', headers={'Authorization': 'Bearer secret'}),
            ), timeout=1)
        assert request_id_context.get() == 'outer-context'
    finally:
        request_id_context.reset(token)
    ids = {response.headers['x-request-id'] for response in responses}
    assert len(ids) == 2 and ids == set(observed) and 'forged-id' not in ids
    assert all(response.json()['request_id'] == response.headers['x-request-id'] for response in responses)
    records = request_records(caplog)
    assert len(records) == 2 and {record.request_id for record in records} == ids
    assert all(record.route == '/wallets/{wallet_id}' and record.status_code == 200 for record in records)
    assert all(record.levelno == logging.INFO and record.duration_ms >= 0 for record in records)
    assert 'sensitive-wallet' not in caplog.text and 'query-secret' not in caplog.text


@pytest.mark.parametrize('path,status_code,level', [('/handled/private-id', 409, logging.WARNING),
                                                  ('/missing/private-id', 404, logging.WARNING),
                                                  ('/failure/private-id', 500, logging.ERROR)])
async def test_http_errors_are_logged_once_with_safe_route_and_correlation_id(caplog, path, status_code, level):
    caplog.set_level(logging.INFO, logger='backend.http')
    application = FastAPI()
    application.add_middleware(RequestLoggingMiddleware)
    @application.get('/handled/{wallet_id}')
    async def handled(wallet_id: str):
        raise HTTPException(409, 'wallet_closed')
    @application.get('/failure/{wallet_id}')
    async def failure(wallet_id: str):
        raise RuntimeError('postgres://admin:secret@private-host/db')
    async with AsyncClient(transport=ASGITransport(app=application, raise_app_exceptions=False), base_url='http://test') as client:
        response = await client.get(path, params={'token': 'secret-query'})
    assert response.status_code == status_code and response.headers['x-request-id']
    if status_code == 500:
        assert response.text == 'Internal Server Error'
        assert response.headers['cache-control'] == 'no-store'
    records = request_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.request_id == response.headers['x-request-id'] and record.levelno == level
    assert record.route == ('unmatched' if status_code == 404 else path.rsplit('/', 1)[0] + '/{wallet_id}')
    assert 'private-id' not in caplog.text and 'secret' not in caplog.text
    if status_code == 500:
        assert record.error_type == 'RuntimeError'
    assert request_id_context.get() is None


async def test_middleware_preserves_streaming_chunks_and_does_not_read_or_wrap_receive(caplog):
    caplog.set_level(logging.INFO, logger='backend.http')
    receive = AsyncMock(side_effect=AssertionError('Middleware must not read the request body'))
    send = AsyncMock()
    async def streaming(scope, actual_receive, actual_send):
        assert actual_receive is receive
        await actual_send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await actual_send({'type': 'http.response.body', 'body': b'first', 'more_body': True})
        await asyncio.sleep(0)
        await actual_send({'type': 'http.response.body', 'body': b'second', 'more_body': False})
    scope = {'type': 'http', 'method': 'POST', 'path': '/private-token', 'query_string': b'password=secret',
             'headers': [(b'authorization', b'Bearer secret')], 'route': SimpleNamespace(path='/stream/{token}')}
    await RequestLoggingMiddleware(streaming)(scope, receive, send)
    receive.assert_not_awaited()
    assert [call.args[0]['body'] for call in send.await_args_list[1:]] == [b'first', b'second']
    assert send.await_args_list[1].args[0]['more_body'] is True
    assert send.await_args_list[2].args[0]['more_body'] is False
    assert request_records(caplog)[0].route == '/stream/{token}'
    assert 'private-token' not in caplog.text and 'password' not in caplog.text


@pytest.mark.parametrize('started', [False, True])
@pytest.mark.parametrize('cancel', [False, True])
async def test_exceptions_are_rethrown_and_context_reset_without_second_response(caplog, started, cancel):
    caplog.set_level(logging.INFO, logger='backend.http')
    receive, send = AsyncMock(), AsyncMock()
    failure = asyncio.CancelledError() if cancel else RuntimeError('sensitive-error-detail')
    async def broken(scope, actual_receive, actual_send):
        if started:
            await actual_send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await actual_send({'type': 'http.response.body', 'body': b'partial', 'more_body': True})
        raise failure
    scope = {'type': 'http', 'method': 'GET', 'path': '/private-id', 'headers': []}
    token = request_id_context.set('outer-context')
    try:
        with pytest.raises(type(failure)) as caught:
            await RequestLoggingMiddleware(broken)(scope, receive, send)
        assert caught.value is failure
        assert request_id_context.get() == 'outer-context'
    finally:
        request_id_context.reset(token)
    starts = [call.args[0] for call in send.await_args_list if call.args[0]['type'] == 'http.response.start']
    assert len(starts) == (0 if cancel and not started else 1)
    record = request_records(caplog)[0]
    assert record.status_code == (200 if started else 499 if cancel else 500)
    assert record.error_type == ('CancelledError' if cancel else 'RuntimeError')
    assert 'sensitive-error-detail' not in caplog.text
    if not cancel and not started:
        assert send.await_args_list[-1].args[0]['body'] == b'Internal Server Error'
        assert dict(starts[0]['headers'])[b'x-request-id'].decode() == record.request_id
    receive.assert_not_awaited()


async def test_non_http_scope_passes_through_without_http_context_or_logs(caplog):
    downstream = AsyncMock()
    receive, send = AsyncMock(), AsyncMock()
    scope = {'type': 'websocket', 'path': '/socket'}
    await RequestLoggingMiddleware(downstream)(scope, receive, send)
    downstream.assert_awaited_once_with(scope, receive, send)
    assert not request_records(caplog)
    assert 'state' not in scope

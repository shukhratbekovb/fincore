import asyncio
import logging
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.infrastructure.logging import request_id_context


logger = logging.getLogger('backend.http')


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault('state', {})['request_id'] = request_id
        context_token = request_id_context.set(request_id)
        started = perf_counter()
        status_code = 500
        response_started = False
        error_type = None

        async def send_response(message: Message) -> None:
            nonlocal status_code, response_started
            if message['type'] == 'http.response.start':
                status_code = message['status']
                response_started = True
                MutableHeaders(scope=message)['X-Request-ID'] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except asyncio.CancelledError:
            error_type = 'CancelledError'
            if not response_started:
                status_code = 499
            raise
        except Exception as exc:
            error_type = type(exc).__name__
            if not response_started:
                # Preserve the generic 500 contract and attach the correlation ID.
                await PlainTextResponse('Internal Server Error', status_code=500,
                                        headers={'Cache-Control': 'no-store'})(scope, receive, send_response)
            raise
        finally:
            try:
                # FastAPI's included routers retain the original route in
                # scope['route']; the effective context holds its full template.
                effective_route = scope.get('fastapi', {}).get('effective_route_context')
                route = getattr(effective_route, 'path_format', None) or getattr(scope.get('route'), 'path', 'unmatched')
                level = logging.ERROR if error_type or status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
                logger.log(level, 'http_request', extra={
                    'request_id': request_id,
                    'method': scope['method'],
                    # Never record raw paths, query strings, headers or bodies.
                    'route': route,
                    'status_code': status_code,
                    'duration_ms': round((perf_counter() - started) * 1000, 3),
                    **({'error_type': error_type} if error_type else {}),
                })
            finally:
                request_id_context.reset(context_token)

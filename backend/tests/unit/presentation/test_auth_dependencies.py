from datetime import timedelta
from typing import Annotated
from unittest.mock import AsyncMock

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from backend.application.auth.use_cases.register import RegisterUserUseCase
from backend.infrastructure.settings import Settings, get_settings
from backend.presentation.api.v1.dependencies.auth import get_register_use_case
from backend.presentation.api.v1.dependencies.core import get_uow


async def test_registration_dependency_uses_configured_ttl():
    app = FastAPI()
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://test:test@localhost/test',
                        verification_confirmation_ttl='PT15M')
    uow = AsyncMock()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_uow] = lambda: uow

    @app.get('/dependency-test')
    def endpoint(use_case: Annotated[RegisterUserUseCase, Depends(get_register_use_case)]):
        assert use_case.uow is uow
        assert use_case.confirmation_ttl == timedelta(minutes=15)
        assert use_case.clock.now().tzinfo is not None
        return {'ttl_seconds': use_case.confirmation_ttl.total_seconds()}

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/dependency-test')
    assert response.status_code == 200
    assert response.json() == {'ttl_seconds': 900}


async def test_login_dependency_uses_session_ttl_and_token_hasher():
    from backend.application.auth.use_cases.login import LoginUserUseCase
    from backend.presentation.api.v1.dependencies.auth import get_login_use_case

    app = FastAPI()
    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://test:test@localhost/test',
                        jwt_secret_key='test-jwt-secret-at-least-32-bytes-long', session_ttl='P7D')
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_uow] = lambda: AsyncMock()

    @app.get('/dependency-test')
    def endpoint(use_case: Annotated[LoginUserUseCase, Depends(get_login_use_case)]):
        assert use_case.token_hasher.hash('test')
        return {'ttl_seconds': use_case.session_ttl.total_seconds()}

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/dependency-test')
    assert response.status_code == 200
    assert response.json() == {'ttl_seconds': timedelta(days=7).total_seconds()}


async def test_resend_dependency_uses_registration_confirmation_ttl():
    from backend.presentation.api.v1.dependencies.auth import get_resend_confirmation_use_case

    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://test:test@localhost/test',
                        verification_confirmation_ttl='PT20M')
    uow = AsyncMock()
    from backend.infrastructure.clock import SystemClock
    from backend.infrastructure.security.token_generator import TokenGenerator
    from backend.infrastructure.security.token_hasher import TokenHasher
    use_case = get_resend_confirmation_use_case(uow, TokenGenerator(), TokenHasher(), SystemClock(), settings)
    assert use_case.uow is uow
    assert use_case.confirmation_ttl == timedelta(minutes=20)

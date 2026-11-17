from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.application.session.errors import SessionNotFoundError
from backend.presentation.api.errors import register_exception_handlers


async def test_session_not_found_has_registered_generic_404_response():
    app = FastAPI()
    register_exception_handlers(app)

    @app.delete('/sessions/{session_id}')
    async def remove_session(session_id: str):
        raise SessionNotFoundError()

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.delete('/sessions/unknown-session')

    assert response.status_code == 404
    assert response.json() == {
        'detail': {'code': 'session_not_found', 'message': 'Session not found', 'errors': []},
    }

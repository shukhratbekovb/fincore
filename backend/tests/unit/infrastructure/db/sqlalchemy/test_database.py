from unittest.mock import Mock

from sqlalchemy.ext.asyncio import AsyncSession

from backend.infrastructure.db.sqlalchemy.core import database
from backend.infrastructure.settings import Settings


def settings():
    return Settings(_env_file=None, database_url='postgresql+asyncpg://test:test@localhost/test')


def test_engine_configuration_without_connecting(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(database, 'create_async_engine', factory)
    config = settings()
    result = database.create_engine(config)
    assert result is factory.return_value
    factory.assert_called_once_with(
        config.database_url.get_secret_value(), pool_pre_ping=True,
        pool_size=5, max_overflow=10, pool_timeout=30,
        hide_parameters=True, connect_args={'server_settings': {'timezone': 'UTC'}},
    )


async def test_real_engine_and_session_factory_require_no_connection():
    engine = database.create_engine(settings())
    try:
        factory = database.create_session_factory(engine)
        async with factory() as first, factory() as second:
            assert isinstance(first, AsyncSession)
            assert first is not second
            assert first.bind is engine
            assert first.sync_session.expire_on_commit is False
    finally:
        await engine.dispose()

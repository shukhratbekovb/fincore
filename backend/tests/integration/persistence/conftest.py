import os
from uuid import uuid4

import pytest
from sqlalchemy import schema
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyBaseModel


@pytest.fixture
async def session_factory():
    url = os.environ.get('FINCORE_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set FINCORE_TEST_DATABASE_URL to a dedicated PostgreSQL test database')
    parsed = make_url(url)
    if parsed.drivername != 'postgresql+asyncpg' or not parsed.database or not parsed.database.endswith('_test'):
        pytest.fail('FINCORE_TEST_DATABASE_URL must use asyncpg and a database ending in _test')
    namespace = 'repo_test_' + uuid4().hex
    engine = create_async_engine(url, hide_parameters=True, connect_args={
        'server_settings': {'search_path': namespace, 'timezone': 'UTC', 'statement_timeout': '5000'},
    })
    try:
        async with engine.begin() as connection:
            await connection.execute(schema.CreateSchema(namespace))
            await connection.run_sync(SqlAlchemyBaseModel.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as connection:
            await connection.execute(schema.DropSchema(namespace, cascade=True, if_exists=True))
        await engine.dispose()

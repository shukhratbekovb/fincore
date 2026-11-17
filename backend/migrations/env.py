import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyBaseModel
from backend.infrastructure.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = SqlAlchemyBaseModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_with_connection(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(
        get_settings().database_url.get_secret_value(), poolclass=NullPool,
        hide_parameters=True, connect_args={'server_settings': {'timezone': 'UTC'}},
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_with_connection)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif config.attributes.get('connection') is not None:
    run_with_connection(config.attributes['connection'])
else:
    asyncio.run(run_async_migrations())

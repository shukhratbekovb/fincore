import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from backend.application.auth.dtos.confirm import ConfirmUserCommand
from backend.application.auth.dtos.register import RegisterUserCommand
from backend.application.auth.dtos.refresh import RefreshSessionCommand
from backend.application.auth.dtos.change_password import ChangePasswordCommand
from backend.application.auth.dtos.logout import LogoutUserCommand
from backend.application.auth.errors import EmailAlreadyExistError, UsernameAlreadyExistError
from backend.application.auth.use_cases.register import RegisterUserUseCase
from backend.application.auth.use_cases.confirm import ConfirmUserUseCase
from backend.application.auth.use_cases.refresh import RefreshSessionUseCase
from backend.application.auth.use_cases.change_password import ChangePasswordUseCase
from backend.application.auth.use_cases.logout import LogoutUserUseCase
from backend.application.share.errors import EntityNotFoundError
from backend.application.wallet.dtos.create_wallet import CreateWalletCommand
from backend.application.wallet.dtos.close_wallet import CloseWalletCommand
from backend.application.wallet.dtos.rename_wallet import RenameWalletCommand
from backend.application.wallet.use_cases.create_wallet import CreateWalletUseCase
from backend.application.wallet.use_cases.close_wallet import CloseWalletUseCase
from backend.application.wallet.use_cases.rename_wallet import RenameWalletUseCase
from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.session.entities import Session, RefreshToken
from backend.domain.session.errors import RefreshTokenReuseError
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, Username, HashedPassword, RawPassword
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.enums import WalletStatusEnum
from backend.domain.wallet.value_objects import WalletName, WalletNumber
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork
from backend.infrastructure.db.sqlalchemy.models import (
    SqlAlchemyUserModel, SqlAlchemyWalletModel, SqlAlchemyWalletBalanceModel,
    SqlAlchemyLedgerAccountModel, SqlAlchemyOutboxModel, SqlAlchemySessionModel,
)
from backend.infrastructure.wallet.number_generator import RandomWalletNumberGenerator

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)
CLOCK = SimpleNamespace(now=lambda: NOW)


async def add_user(factory, suffix='alice'):
    user = User.created_by_admin(Username(suffix), Email(suffix + '@example.com'), HashedPassword('old-hash'))
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.users.add(user)
        await uow.commit()
    return user


async def seed_session(factory, user):
    session = Session.create(user_id=user.id, ip_address='127.0.0.1', now=NOW, ttl=timedelta(days=1))
    token = RefreshToken(session_id=session.id, token_hash='old', expires_at=session.expires_at)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.sessions.add(session)
        await uow.refresh_tokens.add(token)
        await uow.commit()
    return session, token


async def test_registration_and_confirmation_atomically_persist(session_factory):
    uow = SqlAlchemyUnitOfWork(session_factory)
    register = RegisterUserUseCase(uow, SimpleNamespace(generate=lambda: 'confirmation-secret'),
                                  SimpleNamespace(hash=lambda value: 'digest'), CLOCK, timedelta(hours=1))
    result = await register.execute(RegisterUserCommand(Username('alice'), Email('alice@example.com')))
    async with session_factory() as connection:
        message = (await connection.execute(select(SqlAlchemyOutboxModel))).scalar_one()
        assert message.payload['token'] == 'confirmation-secret'
        assert message.payload['user_id'] == str(result.user_id)
    confirm = ConfirmUserUseCase(uow, SimpleNamespace(hash=lambda value: HashedPassword('new-hash')),
                                SimpleNamespace(hash=lambda value: 'digest'), CLOCK)
    await confirm.execute(ConfirmUserCommand('confirmation-secret', RawPassword('Password1!')))
    async with uow:
        user = await uow.users.get_by_id(result.user_id)
        assert user.status == UserStatusEnum.ACTIVE
        assert user.password_hash.value == 'new-hash'
        challenge = await uow.verification_challenges.get_by_token_hash_for_update('digest')
        assert challenge.used_at == NOW


@pytest.mark.parametrize('failure', ['normal_exit', 'exception'])
async def test_uncommitted_user_rolls_back(session_factory, failure):
    user = User.register(Username('alice'), Email('alice@example.com'))
    try:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.users.add(user)
            if failure == 'exception':
                raise RuntimeError('abort')
    except RuntimeError:
        pass
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert await uow.users.get_by_id(user.id) is None


@pytest.mark.parametrize(('field', 'expected'), [('email', EmailAlreadyExistError), ('username', UsernameAlreadyExistError)])
async def test_postgres_unique_conflict_translation(session_factory, field, expected):
    await add_user(session_factory)
    user = User.register(Username('other') if field == 'email' else Username('alice'),
                         Email('alice@example.com') if field == 'email' else Email('other@example.com'))
    with pytest.raises(expected):
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.users.add(user)
            await uow.commit()


async def test_create_rename_close_wallet_and_linked_records(session_factory):
    user = await add_user(session_factory)
    uow = SqlAlchemyUnitOfWork(session_factory)
    created = await CreateWalletUseCase(uow, RandomWalletNumberGenerator(), CLOCK).execute(
        CreateWalletCommand(user.id, WalletName('Main'), CurrencyEnum.EUR))
    await RenameWalletUseCase(uow).execute(RenameWalletCommand(user.id, created.wallet_id, WalletName('Savings')))
    async with uow:
        wallet = await uow.wallets.get_by_id_for_update(created.wallet_id)
        assert wallet.name.value == 'Savings'
        balance = await uow.wallet_balances.get_by_wallet_id_for_update(wallet.id)
        assert balance.posted_minor == balance.version == 0
        account = await uow.ledger_accounts.get_by_wallet_id_for_update(wallet.id)
        assert account.currency == CurrencyEnum.EUR
    await CloseWalletUseCase(uow).execute(CloseWalletCommand(user.id, created.wallet_id))
    async with uow:
        assert (await uow.wallets.get_by_id_for_update(created.wallet_id)).status == WalletStatusEnum.CLOSED
        assert not (await uow.ledger_accounts.get_by_wallet_id_for_update(created.wallet_id)).is_active()


async def test_wallet_number_collision_retries_whole_transaction(session_factory):
    user = await add_user(session_factory)
    uow = SqlAlchemyUnitOfWork(session_factory)
    numbers = iter([WalletNumber('1' * 20), WalletNumber('1' * 20), WalletNumber('2' * 20)])
    create = CreateWalletUseCase(uow, SimpleNamespace(generate=lambda: next(numbers)), CLOCK)
    await create.execute(CreateWalletCommand(user.id, WalletName('One')))
    await create.execute(CreateWalletCommand(user.id, WalletName('Two')))
    async with session_factory() as session:
        for model in (SqlAlchemyWalletModel, SqlAlchemyWalletBalanceModel, SqlAlchemyLedgerAccountModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 2


async def test_foreign_key_failure_rolls_back_prior_wallet_insert(session_factory):
    user = await add_user(session_factory)
    wallet = Wallet.create(user_id=user.id, name=WalletName('Main'), number=WalletNumber('1' * 20), currency=CurrencyEnum.USD)
    wrong_currency = LedgerAccount.for_wallet(wallet_id=wallet.id, currency=CurrencyEnum.EUR, now=NOW)
    with pytest.raises(IntegrityError):
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.wallets.add(wallet)
            await uow.ledger_accounts.add(wrong_currency)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert await uow.wallets.get_by_id_for_update(wallet.id) is None


async def test_balance_save_and_nonnegative_database_constraint(session_factory):
    user = await add_user(session_factory)
    uow = SqlAlchemyUnitOfWork(session_factory)
    wallet = await CreateWalletUseCase(uow, RandomWalletNumberGenerator(), CLOCK).execute(CreateWalletCommand(user.id, WalletName('Main')))
    async with uow:
        balance = await uow.wallet_balances.get_by_wallet_id_for_update(wallet.wallet_id)
        balance.credit(100, now=NOW)
        await uow.wallet_balances.save(balance)
        await uow.commit()
    async with uow:
        balance = await uow.wallet_balances.get_by_wallet_id_for_update(wallet.wallet_id)
        assert balance.posted_minor == 100 and balance.version == 1
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            await session.execute(update(SqlAlchemyWalletBalanceModel).values(posted_minor=-1))


async def test_refresh_rotates_and_reuse_revokes_session(session_factory):
    user = await add_user(session_factory)
    session, token = await seed_session(session_factory, user)
    use_case = RefreshSessionUseCase(SqlAlchemyUnitOfWork(session_factory), SimpleNamespace(encode=lambda user_id: 'access'),
        SimpleNamespace(generate=lambda: 'new'), SimpleNamespace(hash=lambda value: value), CLOCK, timedelta(days=1))
    result = await use_case.execute(RefreshSessionCommand('old', '127.0.0.2', 'Browser'))
    assert result.refresh_token == 'new'
    with pytest.raises(RefreshTokenReuseError):
        await use_case.execute(RefreshSessionCommand('old', '127.0.0.1'))
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert (await uow.sessions.get_by_id(session.id)).revoked_at == NOW
        old = await uow.refresh_tokens.get_by_token_hash('old')
        new = await uow.refresh_tokens.get_by_token_hash('new')
        assert old.replaced_by_id == new.id and new.session_id == session.id


async def test_password_change_revokes_sessions_and_logout_preserves_revocation(session_factory):
    user = await add_user(session_factory)
    session, _ = await seed_session(session_factory, user)
    uow = SqlAlchemyUnitOfWork(session_factory)
    hasher = SimpleNamespace(verify=lambda raw, hashed: hashed.value == 'old-hash', hash=lambda raw: HashedPassword('new-hash'))
    await ChangePasswordUseCase(uow, hasher, CLOCK).execute(ChangePasswordCommand(user.id, RawPassword('OldPass1!'), RawPassword('NewPass1!')))
    await LogoutUserUseCase(uow, SimpleNamespace(hash=lambda value: value), CLOCK).execute(LogoutUserCommand('old'))
    async with uow:
        assert (await uow.users.get_by_id(user.id)).password_hash.value == 'new-hash'
        assert (await uow.sessions.get_by_id(session.id)).revoked_at == NOW


async def test_postgres_for_update_waits_and_reads_current_state(session_factory):
    user = await add_user(session_factory)
    async with SqlAlchemyUnitOfWork(session_factory) as first, SqlAlchemyUnitOfWork(session_factory) as second:
        # Retain a cached ORM object to exercise populate_existing as well.
        cached = await second.session.get(SqlAlchemyUserModel, user.id)
        locked = await first.users.get_by_id_for_update(user.id)
        task = asyncio.create_task(second.users.get_by_id_for_update(user.id))
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.15)
            locked.suspend()
            await first.users.save(locked)
            await first.commit()
            current = await asyncio.wait_for(task, timeout=3)
            assert current.status == UserStatusEnum.SUSPENDED
            assert cached.status == 'suspended'
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_login_persists_device_and_refresh_token(session_factory):
    from backend.application.auth.dtos.login import LoginUserCommand
    from backend.application.auth.use_cases.login import LoginUserUseCase

    user = await add_user(session_factory)
    uow = SqlAlchemyUnitOfWork(session_factory)
    use_case = LoginUserUseCase(uow, SimpleNamespace(verify=lambda *args: True),
        SimpleNamespace(encode=lambda user_id: 'access'), SimpleNamespace(generate=lambda: 'new'),
        SimpleNamespace(hash=lambda value: 'digest'), CLOCK, timedelta(days=1))
    result = await use_case.execute(LoginUserCommand(user.username, RawPassword('Password1!'), '127.0.0.1', 'Test browser'))
    assert result.refresh_token == 'new'
    async with uow:
        token = await uow.refresh_tokens.get_by_token_hash('digest')
        session = await uow.sessions.get_by_id(token.session_id)
        assert session.user_id == user.id and session.user_agent == 'Test browser'
        assert (await uow.users.get_by_id(user.id)).last_login_at is not None


async def test_simultaneous_refresh_only_rotates_once_then_revokes(session_factory):
    user = await add_user(session_factory)
    session, _ = await seed_session(session_factory, user)

    async def refresh():
        use_case = RefreshSessionUseCase(SqlAlchemyUnitOfWork(session_factory), SimpleNamespace(encode=lambda user_id: 'access'),
            SimpleNamespace(generate=lambda: 'new'), SimpleNamespace(hash=lambda value: value), CLOCK, timedelta(days=1))
        return await use_case.execute(RefreshSessionCommand('old', '127.0.0.1'))

    results = await asyncio.wait_for(asyncio.gather(refresh(), refresh(), return_exceptions=True), timeout=5)
    assert sum(isinstance(result, RefreshTokenReuseError) for result in results) == 1
    assert sum(getattr(result, 'refresh_token', None) == 'new' for result in results) == 1
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert (await uow.sessions.get_by_id(session.id)).revoked_at == NOW


async def test_initial_migration_upgrade_downgrade_and_model_parity(session_factory):
    from pathlib import Path
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyBaseModel

    config = Config(str(Path(__file__).resolve().parents[3] / 'alembic.ini'))
    async with session_factory.kw['bind'].begin() as connection:
        await connection.run_sync(SqlAlchemyBaseModel.metadata.drop_all)
        def migrate(sync_connection):
            config.attributes['connection'] = sync_connection
            command.upgrade(config, 'head')
            assert compare_metadata(MigrationContext.configure(sync_connection), SqlAlchemyBaseModel.metadata) == []
            command.downgrade(config, 'base')
            command.upgrade(config, 'head')
        await connection.run_sync(migrate)

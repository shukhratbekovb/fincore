from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.auth.errors import EmailAlreadyExistError, UsernameAlreadyExistError
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, Username
from backend.infrastructure.db.sqlalchemy.core import uow as uow_module
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork


@pytest.fixture
def ctx():
    session = AsyncMock(spec=AsyncSession)
    factory = Mock(return_value=session)
    return session, factory, SqlAlchemyUnitOfWork(factory)


async def test_no_commit_means_rollback_and_close(ctx):
    session, factory, uow = ctx
    async with uow as entered:
        assert entered is uow
        assert uow.users.session is session
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()
    session.commit.assert_not_awaited()
    with pytest.raises(RuntimeError):
        _ = uow.users


async def test_explicit_commit_cleanup_order(ctx):
    session, factory, uow = ctx
    operations = []
    for label in ('commit', 'rollback', 'close'):
        getattr(session, label).side_effect = lambda label=label: operations.append(label)
    async with uow:
        await uow.commit()
    assert operations == ['commit', 'rollback', 'close']


async def test_reentry_uses_fresh_session(ctx):
    first, factory, uow = ctx
    second = AsyncMock(spec=AsyncSession)
    factory.side_effect = [first, second]
    async with uow:
        first_repo = uow.users
        first_reader = uow.wallet_reader
        assert first_reader.session is first
    async with uow:
        assert uow.session is second
        assert uow.users is not first_repo
        assert uow.wallet_reader is not first_reader
        assert uow.wallet_reader.session is second
    first.close.assert_awaited_once()
    second.close.assert_awaited_once()


async def test_nested_entry_rejected_without_overwriting_active_session(ctx):
    session, factory, uow = ctx
    async with uow:
        with pytest.raises(RuntimeError, match='already active'):
            await uow.__aenter__()
        assert uow.session is session
    factory.assert_called_once()


@pytest.mark.parametrize('stage', ['body', 'commit'])
async def test_operation_failure_rolls_back_closes_and_propagates(ctx, stage):
    session, factory, uow = ctx
    if stage == 'commit':
        session.commit.side_effect = ValueError('failed')
    with pytest.raises(ValueError, match='failed'):
        async with uow:
            if stage == 'commit':
                await uow.commit()
            else:
                raise ValueError('failed')
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.parametrize('stage', ['rollback', 'close'])
async def test_cleanup_failure_still_clears_session(ctx, stage):
    session, factory, uow = ctx
    getattr(session, stage).side_effect = RuntimeError('cleanup failed')
    with pytest.raises(RuntimeError, match='cleanup failed'):
        async with uow:
            pass
    session.close.assert_awaited_once()
    with pytest.raises(RuntimeError, match='entered first'):
        _ = uow.session
    with pytest.raises(RuntimeError, match='entered first'):
        _ = uow.wallet_reader


@pytest.mark.parametrize('adapter', ['SqlAlchemyUserRepository', 'SqlAlchemyWalletReader',
                                   'SqlAlchemyTransferRepository', 'SqlAlchemyTransactionHistoryReader'])
async def test_failed_adapter_setup_closes_session(ctx, monkeypatch, adapter):
    session, factory, uow = ctx
    monkeypatch.setattr(uow_module, adapter, Mock(side_effect=RuntimeError('setup failed')))
    with pytest.raises(RuntimeError, match='setup failed'):
        await uow.__aenter__()
    session.close.assert_awaited_once()
    with pytest.raises(RuntimeError):
        _ = uow.session
    with pytest.raises(RuntimeError, match='entered first'):
        _ = uow.users
    with pytest.raises(RuntimeError, match='entered first'):
        _ = uow.wallet_reader


async def test_failed_reader_setup_allows_reentry_with_fresh_session(ctx, monkeypatch):
    first, factory, uow = ctx
    second = AsyncMock(spec=AsyncSession)
    factory.side_effect = [first, second]
    reader_type = uow_module.SqlAlchemyWalletReader

    def build_reader(session):
        if session is first:
            raise RuntimeError('reader setup failed')
        return reader_type(session)

    monkeypatch.setattr(uow_module, 'SqlAlchemyWalletReader', build_reader)
    with pytest.raises(RuntimeError, match='reader setup failed'):
        await uow.__aenter__()
    first.close.assert_awaited_once()
    async with uow:
        assert uow.wallet_reader.session is second
        assert uow.users.session is second
    second.close.assert_awaited_once()


async def test_explicit_rollback(ctx):
    session, factory, uow = ctx
    async with uow:
        await uow.rollback()
        session.rollback.assert_awaited_once()


@pytest.mark.parametrize('method', ['commit', 'rollback'])
async def test_transaction_methods_require_context(ctx, method):
    with pytest.raises(RuntimeError, match='entered first'):
        await getattr(ctx[2], method)()


def integrity_error(constraint, sqlstate='23505', chained=False):
    original = Exception('database violation')
    original.sqlstate = sqlstate
    diagnostic = Exception('constraint violation') if chained else original
    diagnostic.constraint_name = constraint
    if chained:
        original.__cause__ = diagnostic
    return IntegrityError('INSERT', {}, original)


@pytest.mark.parametrize(('constraint', 'error'), [('ix_users_email', EmailAlreadyExistError), ('ix_users_username', UsernameAlreadyExistError)])
@pytest.mark.parametrize('stage', ['flush', 'commit'])
@pytest.mark.parametrize('chained', [False, True])
async def test_unique_conflicts_translated_after_cleanup(ctx, constraint, error, stage, chained):
    session, factory, uow = ctx
    violation = integrity_error(constraint, chained=chained)
    getattr(session, stage).side_effect = violation
    with pytest.raises(error) as caught:
        async with uow:
            if stage == 'flush':
                await uow.users.add(User.register(Username('alice'), Email('alice@example.com')))
            else:
                await uow.commit()
    assert caught.value.__cause__ is violation
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.parametrize(('constraint', 'sqlstate'), [('other_index', '23505'), ('ix_users_email', '23503'), (None, '23505')])
async def test_unrelated_integrity_error_is_not_relabelled(ctx, constraint, sqlstate):
    session, factory, uow = ctx
    violation = integrity_error(constraint, sqlstate)
    with pytest.raises(IntegrityError) as caught:
        async with uow:
            raise violation
    assert caught.value is violation


@pytest.mark.parametrize('name', ['users', 'sessions', 'refresh_tokens', 'verification_challenges', 'wallets', 'wallet_balances', 'ledger_accounts', 'outbox', 'wallet_reader',
                                 'transfers', 'sandbox_top_ups', 'ledger_transactions', 'idempotency', 'transfer_reader',
                                 'transaction_history_reader', 'wallet_balance_reader', 'sandbox_operator_reader'])
async def test_all_adapters_share_session_and_are_unavailable_after_exit(ctx, name):
    session, factory, uow = ctx
    with pytest.raises(RuntimeError, match='entered first'):
        getattr(uow, name)
    async with uow:
        assert getattr(uow, name).session is session
    with pytest.raises(RuntimeError, match='entered first'):
        getattr(uow, name)


async def test_wallet_number_conflict_translates_without_relabelling_account_conflicts(ctx):
    from backend.application.wallet.errors import WalletNumberAlreadyExistsError

    session, factory, uow = ctx
    with pytest.raises(WalletNumberAlreadyExistsError):
        async with uow:
            raise integrity_error('uq_wallets_number')
    with pytest.raises(IntegrityError):
        async with uow:
            raise integrity_error('uq_ledger_accounts_code')

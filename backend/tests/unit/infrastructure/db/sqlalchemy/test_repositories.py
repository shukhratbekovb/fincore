from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.share.errors import EntityNotFoundError, UnsupportedOutboxMessageError
from backend.application.share.messages import OutboxMessage
from backend.application.user.errors import UserNotFoundError
from backend.application.verification.messages import SendRegistrationConfirmation
from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.session.entities import Session, RefreshToken
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, Username
from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.value_objects import WalletName, WalletNumber
from backend.domain.wallet_balance.entities import WalletBalance
from backend.infrastructure.db.sqlalchemy.repository.user import SqlAlchemyUserRepository
from backend.infrastructure.db.sqlalchemy.repository.wallet import SqlAlchemyWalletRepository
from backend.infrastructure.db.sqlalchemy.repository.session import SqlAlchemySessionRepository
from backend.infrastructure.db.sqlalchemy.repository.refresh_token import SqlAlchemyRefreshTokenRepository
from backend.infrastructure.db.sqlalchemy.repository.verification import SqlAlchemyVerificationChallengeRepository
from backend.infrastructure.db.sqlalchemy.repository.wallet_balance import SqlAlchemyWalletBalanceRepository
from backend.infrastructure.db.sqlalchemy.repository.ledger_account import SqlAlchemyLedgerAccountRepository
from backend.infrastructure.db.sqlalchemy.repository.outbox import SqlAlchemyOutbox

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)
USER = User.register(Username('alice'), Email('alice@example.com'))
WALLET = Wallet.create(user_id=USER.id, name=WalletName('Main'), number=WalletNumber('1' * 20), currency=CurrencyEnum.USD)
SESSION = Session.create(user_id=USER.id, ip_address='127.0.0.1', now=NOW, ttl=timedelta(days=1))
CASES = [
    (SqlAlchemyUserRepository, USER, 'get_by_id', USER.id, False),
    (SqlAlchemyUserRepository, USER, 'get_by_id_for_update', USER.id, True),
    (SqlAlchemyUserRepository, USER, 'get_by_email', USER.email, False),
    (SqlAlchemyUserRepository, USER, 'get_by_username', USER.username, False),
    (SqlAlchemyWalletRepository, WALLET, 'get_by_id_for_update', WALLET.id, True),
    (SqlAlchemySessionRepository, SESSION, 'get_by_id', SESSION.id, False),
    (SqlAlchemySessionRepository, SESSION, 'get_by_id_for_update', SESSION.id, True),
]
TOKEN = RefreshToken(session_id=SESSION.id, token_hash='digest', expires_at=NOW + timedelta(days=1))
CASES += [
    (SqlAlchemyRefreshTokenRepository, TOKEN, 'get_by_token_hash', TOKEN.token_hash, False),
    (SqlAlchemyRefreshTokenRepository, TOKEN, 'get_by_id_for_update', TOKEN.id, True),
    (SqlAlchemyVerificationChallengeRepository, VerificationChallenge(user_id=USER.id, purpose=VerificationPurpose.REGISTRATION, token_hash='challenge-hash', expires_at=NOW + timedelta(hours=1)), 'get_by_token_hash_for_update', 'challenge-hash', True),
    (SqlAlchemyWalletBalanceRepository, WalletBalance.create(wallet_id=WALLET.id, now=NOW), 'get_by_wallet_id_for_update', WALLET.id, True),
    (SqlAlchemyLedgerAccountRepository, LedgerAccount.for_wallet(wallet_id=WALLET.id, currency=WALLET.currency, now=NOW), 'get_by_wallet_id_for_update', WALLET.id, True),
]


@pytest.mark.parametrize('repo_type,entity,method,key,locked', CASES)
async def test_add_read_roundtrip_and_lock_query(repo_type, entity, method, key, locked):
    session = AsyncMock(spec=AsyncSession)
    repository = repo_type(session)
    await repository.add(entity)
    model = session.add.call_args.args[0]
    result = Mock()
    result.scalar_one_or_none.return_value = model
    session.execute.return_value = result
    restored = await getattr(repository, method)(key)
    assert restored == entity
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=dialect()))
    assert ('FOR UPDATE' in sql) == locked
    if locked:
        assert statement.get_execution_options()['populate_existing'] is True
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.parametrize('repo_type,entity,method,key,locked', CASES)
async def test_missing_reads_return_none(repo_type, entity, method, key, locked):
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    assert await getattr(repo_type(session), method)(key) is None


SAVE_CASES = [case for case in CASES if case[2] in {'get_by_id_for_update', 'get_by_token_hash_for_update', 'get_by_wallet_id_for_update'}]


@pytest.mark.parametrize('repo_type,entity,method,key,locked', SAVE_CASES)
async def test_save_updates_existing_rows_only(repo_type, entity, method, key, locked):
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalar_one_or_none.return_value = uuid4()
    session.execute.return_value = result
    await repo_type(session).save(entity)
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=dialect()))
    assert sql.startswith('UPDATE ') and 'RETURNING' in sql
    assert 'created_at' not in statement.compile().params
    session.merge.assert_not_awaited()
    session.commit.assert_not_awaited()
    result.scalar_one_or_none.return_value = None
    error = UserNotFoundError if repo_type is SqlAlchemyUserRepository else EntityNotFoundError
    with pytest.raises(error):
        await repo_type(session).save(entity)


async def test_revoke_all_filters_user_and_preserves_old_revocation():
    session = AsyncMock(spec=AsyncSession)
    await SqlAlchemySessionRepository(session).revoke_all_by_user_id(USER.id, now=NOW)
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=dialect()))
    assert 'sessions.user_id =' in sql
    assert 'sessions.revoked_at IS NULL' in sql
    assert statement.compile().params['revoked_at'] == NOW


async def test_outbox_serializes_explicit_message_and_rejects_unknown():
    session = AsyncMock(spec=AsyncSession)
    message = SendRegistrationConfirmation(user_id=USER.id, email=USER.email, token='secret', expires_at=NOW)
    repo = SqlAlchemyOutbox(session)
    await repo.add(message)
    model = session.add.call_args.args[0]
    assert model.id == message.id
    assert model.message_type == 'auth.send_registration_confirmation.v1'
    assert model.payload == dict(user_id=str(USER.id), email=USER.email.value, token='secret', expires_at=NOW.isoformat())
    with pytest.raises(UnsupportedOutboxMessageError):
        await repo.add(OutboxMessage())
    custom = SqlAlchemyOutbox(session, serializers={OutboxMessage: ('test.v1', lambda item: {})})
    await custom.add(OutboxMessage())
    assert session.add.call_args.args[0].message_type == 'test.v1'


def test_outbox_explicit_mappers_roundtrip_and_unknown_type():
    from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyOutboxModel
    from backend.infrastructure.db.sqlalchemy.repository.outbox import _to_entity, _to_model

    message = SendRegistrationConfirmation(user_id=USER.id, email=USER.email, token='secret', expires_at=NOW)
    assert _to_entity(_to_model(message)) == message
    model = SqlAlchemyOutboxModel(id=uuid4(), message_type='unknown.v1', payload={})
    with pytest.raises(UnsupportedOutboxMessageError):
        _to_entity(model)
    restored = _to_entity(model, {'unknown.v1': lambda item: OutboxMessage(id=item.id)})
    assert restored.id == model.id

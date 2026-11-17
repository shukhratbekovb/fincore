import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from backend.application.verification.messages import SendRegistrationConfirmation
from backend.domain.user.value_objects import Email
from backend.infrastructure.db.sqlalchemy.models.outbox import SqlAlchemyOutboxModel
from backend.infrastructure.db.sqlalchemy.repository.outbox import SqlAlchemyOutbox
from backend.infrastructure.db.sqlalchemy.repository.outbox_queue import SqlAlchemyOutboxQueue


async def add_message(factory):
    message = SendRegistrationConfirmation(user_id=uuid4(), email=Email('alice@example.com'), token='test-secret', expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    async with factory.begin() as session:
        await SqlAlchemyOutbox(session).add(message)
    return message


async def test_concurrent_claims_never_claim_same_live_lease(session_factory):
    messages = [await add_message(session_factory) for _ in range(8)]
    queue = SqlAlchemyOutboxQueue(session_factory)
    batches = await asyncio.gather(*(queue.claim(limit=2, lease=timedelta(seconds=60)) for _ in range(4)))
    deliveries = [delivery for batch in batches for delivery in batch]
    assert {delivery.id for delivery in deliveries} == {message.id for message in messages}
    assert len(deliveries) == 8
    assert all(delivery.attempts == 1 for delivery in deliveries)
    assert await queue.claim(limit=8, lease=timedelta(seconds=60)) == []


async def test_claim_skips_row_locked_by_another_transaction(session_factory):
    message = await add_message(session_factory)
    queue = SqlAlchemyOutboxQueue(session_factory)
    async with session_factory.begin() as session:
        await session.execute(select(SqlAlchemyOutboxModel).where(SqlAlchemyOutboxModel.id == message.id).with_for_update())
        assert await asyncio.wait_for(queue.claim(limit=1, lease=timedelta(seconds=60)), timeout=2) == []
    assert len(await queue.claim(limit=1, lease=timedelta(seconds=60))) == 1


async def test_expired_lease_is_reclaimed_and_stale_owner_cannot_finish_or_retry(session_factory):
    await add_message(session_factory)
    queue = SqlAlchemyOutboxQueue(session_factory)
    old, = await queue.claim(limit=1, lease=timedelta(seconds=60))
    async with session_factory.begin() as session:
        await session.execute(update(SqlAlchemyOutboxModel).values(locked_until=func.clock_timestamp() - timedelta(seconds=1)))
    assert not await queue.finish(old, status='sent')
    current, = await queue.claim(limit=1, lease=timedelta(seconds=60))
    assert current.id == old.id and current.lock_token != old.lock_token and current.attempts == 2
    assert not await queue.finish(old, status='sent')
    assert not await queue.retry(old, delay=timedelta(seconds=1), error_code='test')
    assert await queue.finish(current, status='sent')
    async with session_factory() as session:
        model = await session.get(SqlAlchemyOutboxModel, old.id)
        assert model.payload is None and model.status == 'sent'
        assert model.completed_at is not None
        assert await session.scalar(select(SqlAlchemyOutboxModel.payload.is_(None)).where(SqlAlchemyOutboxModel.id == old.id))


async def test_retry_schedule_does_not_lose_secret_or_send_early(session_factory):
    await add_message(session_factory)
    queue = SqlAlchemyOutboxQueue(session_factory)
    old, = await queue.claim(limit=1, lease=timedelta(seconds=60))
    assert await queue.retry(old, delay=timedelta(minutes=1), error_code='temporary')
    assert await queue.claim(limit=1, lease=timedelta(seconds=60)) == []
    async with session_factory.begin() as session:
        model = await session.get(SqlAlchemyOutboxModel, old.id)
        assert model.payload['token'] == 'test-secret'
        assert model.last_error == 'temporary' and model.lock_token is None
        model.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    current, = await queue.claim(limit=1, lease=timedelta(seconds=60))
    assert current.attempts == 2 and current.message.token == 'test-secret'


@pytest.mark.parametrize('problem', ['unknown_type', 'malformed', 'invalid_email', 'invalid_uuid_type', 'empty_token'])
async def test_poison_message_is_retired_without_blocking_queue(session_factory, problem):
    message = await add_message(session_factory)
    async with session_factory.begin() as session:
        model = await session.get(SqlAlchemyOutboxModel, message.id)
        if problem == 'unknown_type':
            model.message_type = 'unknown.v1'
        else:
            payload = dict(model.payload)
            if problem == 'malformed':
                del payload['token']
            elif problem == 'invalid_uuid_type':
                payload['user_id'] = 123
            elif problem == 'empty_token':
                payload['token'] = ''
            else:
                payload['email'] = 'invalid'
            model.payload = payload
    queue = SqlAlchemyOutboxQueue(session_factory)
    assert await queue.claim(limit=1, lease=timedelta(seconds=60)) == []
    async with session_factory() as session:
        model = await session.get(SqlAlchemyOutboxModel, message.id)
        assert model.status == 'failed' and model.payload is None and model.last_error == 'invalid_message'


@pytest.mark.parametrize('status', ['failed', 'expired'])
async def test_terminal_status_scrubs_payload(session_factory, status):
    await add_message(session_factory)
    queue = SqlAlchemyOutboxQueue(session_factory)
    delivery, = await queue.claim(limit=1, lease=timedelta(seconds=60))
    assert await queue.finish(delivery, status=status, error_code='terminal')
    assert not await queue.finish(delivery, status='sent')
    async with session_factory() as session:
        model = await session.get(SqlAlchemyOutboxModel, delivery.id)
        assert model.payload is None and model.status == status


async def test_register_worker_real_smtp_and_confirm_over_http(session_factory, redis_context, monkeypatch):
    smtp_port = os.environ.get('FINCORE_TEST_SMTP_PORT')
    mailpit_url = os.environ.get('FINCORE_TEST_MAILPIT_URL')
    if not smtp_port or not mailpit_url:
        pytest.skip('Set FINCORE_TEST_SMTP_PORT and FINCORE_TEST_MAILPIT_URL to a disposable Mailpit')
    from backend.main import app
    from backend.bootstrap.outbox_worker import build_processor
    from backend.infrastructure.notifications.settings import SmtpSettings, OutboxWorkerSettings
    from backend.infrastructure.settings import Settings, get_settings
    from backend.domain.user.enums import UserStatusEnum
    from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork

    settings = Settings(_env_file=None, database_url='postgresql+asyncpg://test:test@localhost/fincore_test')
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setattr(app.state, 'session_factory', session_factory, raising=False)
    monkeypatch.setattr(app.state, 'rate_limiter', redis_context.limiter, raising=False)
    username = 'user' + uuid4().hex[:12]
    recipient = username + '@example.com'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/v1/auth/register', json={'username': username, 'email': recipient})
        assert response.status_code == 201
        user_id = response.json()['user_id']
        processor = build_processor(session_factory, SmtpSettings(_env_file=None, smtp_port=int(smtp_port), frontend_confirmation_url='http://localhost:3000/confirm'), OutboxWorkerSettings(_env_file=None))
        assert await processor.run_once() == 1
        async with AsyncClient(base_url=mailpit_url) as mailbox:
            messages = (await mailbox.get('/api/v1/messages')).json()['messages']
            sent = next(item for item in messages if any(to['Address'] == recipient for to in item['To']))
            mail = (await mailbox.get('/api/v1/message/' + sent['ID'])).json()
        url = re.search(r'http://localhost:3000/confirm#[^\s]+', mail['Text']).group()
        token = parse_qs(urlsplit(url).fragment)['token'][0]
        response = await client.post('/v1/auth/confirm', json={'token': token, 'password': 'Password1!'})
        assert response.status_code == 204
    async with session_factory() as session:
        model = (await session.execute(select(SqlAlchemyOutboxModel))).scalar_one()
        assert model.status == 'sent' and model.payload is None
    from uuid import UUID
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        user = await uow.users.get_by_id(UUID(user_id))
        assert user.status == UserStatusEnum.ACTIVE and user.password_hash is not None

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from backend.application.maintenance.dtos import CleanupExpiredDataCommand
from backend.application.maintenance.use_cases.cleanup import CleanupExpiredDataUseCase
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Email, HashedPassword, Username
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork
from backend.infrastructure.db.sqlalchemy.maintenance import SqlAlchemyMaintenanceStore
from backend.infrastructure.db.sqlalchemy.models import (
    SqlAlchemySessionModel as Session, SqlAlchemyRefreshTokenModel as RefreshToken,
    SqlAlchemyVerificationChallengeModel as Challenge, SqlAlchemyOutboxModel as Outbox,
    SqlAlchemyIdempotencyModel as Idempotency, SqlAlchemyIdempotencyReceiptModel as Receipt,
    SqlAlchemyLedgerEntryModel as Entry, SqlAlchemyLedgerTransactionModel as Journal,
)
from backend.infrastructure.security.idempotency import idempotency_key_digest
from backend.infrastructure.db.sqlalchemy.repository.idempotency import SqlAlchemyIdempotencyRepository
from .test_finance_endpoints import ctx, balance, top_up, transfer


async def clean(factory, **kwargs):
    return await CleanupExpiredDataUseCase(SqlAlchemyMaintenanceStore(factory)).execute(CleanupExpiredDataCommand(**kwargs))


async def seed_service_data(factory):
    user = User.created_by_admin(Username('cleanup_user'), Email('cleanup@example.com'), HashedPassword('test-hash'))
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.users.add(user)
        await uow.commit()
    async with factory.begin() as session:
        now = await session.scalar(select(func.statement_timestamp()))
        ids = {}
        for name, expires, revoked in (
            ('expired', now - timedelta(days=8), None),
            ('revoked', now + timedelta(days=30), now - timedelta(days=8)),
            ('active', now + timedelta(days=30), None),
            ('recent_expired', now - timedelta(days=1), None),
        ):
            sid, old, latest = uuid4(), uuid4(), uuid4()
            ids[name] = sid
            session.add(Session(id=sid, user_id=user.id, expires_at=expires, revoked_at=revoked,
                                ip_address='192.0.2.1', created_at=now - timedelta(days=40), updated_at=now))
            await session.flush()
            session.add(RefreshToken(id=latest, session_id=sid, token_hash=latest.hex, expires_at=expires))
            await session.flush()
            session.add(RefreshToken(id=old, session_id=sid, token_hash=old.hex, expires_at=expires,
                                     used_at=now - timedelta(days=10), replaced_by_id=latest))
        for age, used in ((8, None), (8, now - timedelta(days=9)), (1, None), (-1, None)):
            session.add(Challenge(user_id=user.id, purpose='registration', token_hash=uuid4().hex,
                                  expires_at=now - timedelta(days=age), used_at=used))
        for status, age in (('sent', 31), ('failed', 31), ('expired', 31), ('sent', 1), ('pending', 31), ('processing', 31)):
            active = status in ('pending', 'processing')
            session.add(Outbox(message_type='test', status=status, payload={'token': 'test'} if active else None,
                created_at=now - timedelta(days=age), completed_at=None if active else now - timedelta(days=age),
                locked_until=now + timedelta(hours=1) if status == 'processing' else None,
                lock_token=uuid4() if status == 'processing' else None))
    return ids


async def count(factory, model):
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_preview_and_batched_cleanup_preserve_active_chains_and_delivery(session_factory):
    ids = await seed_service_data(session_factory)
    preview = await clean(session_factory, dry_run=True, batch_size=1, max_batches=1)
    assert (preview.sessions, preview.refresh_tokens, preview.verification_challenges, preview.outbox_messages) == (2, 4, 2, 3)
    assert await count(session_factory, Session) == 4
    assert await count(session_factory, Outbox) == 6
    first = await clean(session_factory, batch_size=1, max_batches=1)
    assert first.batch_limit_reached and first.sessions == 1 and first.refresh_tokens == 2
    rest = await clean(session_factory, batch_size=1)
    assert not rest.batch_limit_reached
    async with session_factory() as session:
        assert set((await session.scalars(select(Session.id))).all()) == {ids['active'], ids['recent_expired']}
        assert await session.scalar(select(func.count()).select_from(RefreshToken)) == 4
        assert set((await session.scalars(select(Outbox.status))).all()) == {'sent', 'pending', 'processing'}
    empty = await clean(session_factory)
    assert empty.sessions == empty.outbox_messages == empty.verification_challenges == 0


async def test_locked_session_is_skipped_without_blocking_refresh(session_factory):
    ids = await seed_service_data(session_factory)
    async with session_factory.begin() as session:
        await session.execute(select(Session).where(Session.id == ids['expired']).with_for_update())
        report = await asyncio.wait_for(clean(session_factory), timeout=3)
        assert report.sessions == 1  # Other revoked session can be removed.
        assert await session.get(Session, ids['expired']) is not None
    assert (await clean(session_factory)).sessions == 1


async def seed_old_replay(ctx, live_key, old_key, *, days=8):
    async with ctx.factory.begin() as session:
        record = (await session.scalars(select(Idempotency).where(Idempotency.key == live_key))).one()
        now = await session.scalar(select(func.statement_timestamp()))
        aged = Idempotency(id=uuid4(), user_id=record.user_id, scope=record.scope, key=old_key,
            payload_hash=record.payload_hash, resource_id=record.resource_id,
            created_at=now - timedelta(days=days), expires_at=now - timedelta(days=days - 1))
        session.add(aged)
        return aged.id


async def test_archive_preserves_late_transfer_and_topup_replay_and_payload_conflict(ctx):
    funding = await top_up(ctx, key='fund-live')
    moved = await transfer(ctx, key='move-live')
    assert funding.status_code == moved.status_code == 201
    old_key = 'old-"quoted\\key'
    await seed_old_replay(ctx, 'fund-live', 'fund-old')
    await seed_old_replay(ctx, 'move-live', old_key)
    await seed_old_replay(ctx, 'move-live', 'recent-key', days=2)
    before_balance = await balance(ctx)
    preview = await clean(ctx.factory, dry_run=True)
    assert preview.idempotency_records == 2 and preview.receipts_created == 0
    report = await clean(ctx.factory, batch_size=1)
    assert report.idempotency_records == report.receipts_created == 2
    assert await count(ctx.factory, Receipt) == 2
    assert (await transfer(ctx, key=old_key)).json() == moved.json()
    assert (await top_up(ctx, key='fund-old')).json() == funding.json()
    conflict = await transfer(ctx, amount='10001', key=old_key)
    assert conflict.status_code == 409 and conflict.json()['detail']['code'] == 'idempotency_conflict'
    after_balance = await balance(ctx)
    assert {key: value for key, value in after_balance.items() if key != 'as_of'} == {
        key: value for key, value in before_balance.items() if key != 'as_of'
    }
    assert await count(ctx.factory, Journal) == 2 and await count(ctx.factory, Entry) == 4
    assert await count(ctx.factory, Idempotency) == 3  # Live keys and recent-key; no cache recreation on replay.
    async with ctx.factory() as session:
        digest = await session.scalar(select(func.fincore_idempotency_digest(ctx.users[1].id, 'transfer.create', old_key)))
        assert digest == idempotency_key_digest(user_id=ctx.users[1].id, scope='transfer.create', key=old_key)


async def test_concurrent_cleanup_and_replay_never_duplicate_or_erase_financial_rows(ctx):
    assert (await top_up(ctx)).status_code == 201
    original = await transfer(ctx, key='move-live')
    await seed_old_replay(ctx, 'move-live', 'race-key')
    results = await asyncio.wait_for(asyncio.gather(
        clean(ctx.factory, batch_size=1), clean(ctx.factory, batch_size=1),
        *(transfer(ctx, key='race-key') for _ in range(4)),
    ), timeout=10)
    for response in results[2:]:
        assert response.status_code in (201, 409), response.text
        if response.status_code == 201:
            assert response.json() == original.json()
        else:
            assert response.json()['detail']['code'] == 'idempotency_in_progress'
    assert (await transfer(ctx, key='race-key')).json() == original.json()
    assert await count(ctx.factory, Receipt) == 1
    assert await count(ctx.factory, Journal) == 2
    assert (await balance(ctx))['posted_minor'] == '40000'


async def test_database_requires_receipt_and_makes_archived_result_immutable(ctx):
    assert (await top_up(ctx, key='fund-live')).status_code == 201
    aged_id = await seed_old_replay(ctx, 'fund-live', 'guarded-key')
    with pytest.raises(IntegrityError, match='Permanent replay receipt required'):
        async with ctx.factory.begin() as session:
            await session.execute(delete(Idempotency).where(Idempotency.id == aged_id))
    await clean(ctx.factory)
    for statement in (delete(Receipt), update(Receipt).values(resource_id=uuid4()), text('TRUNCATE idempotency_receipts')):
        with pytest.raises(IntegrityError):
            async with ctx.factory.begin() as session:
                await session.execute(statement)


async def test_replay_waiting_for_archive_commit_reads_permanent_result(ctx):
    assert (await top_up(ctx, key='fund-live')).status_code == 201
    aged_id = await seed_old_replay(ctx, 'fund-live', 'waiting-key')
    async with ctx.factory.begin() as session:
        record = (await session.scalars(select(Idempotency).where(Idempotency.id == aged_id).with_for_update())).one()
        await SqlAlchemyMaintenanceStore._archive_receipts(session, [record])
        await session.execute(delete(Idempotency).where(Idempotency.id == aged_id))
        replay = asyncio.create_task(top_up(ctx, key='waiting-key'))
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(replay), timeout=0.15)
            await session.commit()
            response = await asyncio.wait_for(replay, timeout=3)
            assert response.status_code == 201, response.text
            assert response.json()['top_up_id'] == str(record.resource_id)
        finally:
            if not replay.done():
                replay.cancel()
                await asyncio.gather(replay, return_exceptions=True)
    assert await count(ctx.factory, Journal) == 1


async def test_receipt_mismatch_rolls_back_archive_without_deleting_cache(ctx):
    assert (await top_up(ctx, key='fund-live')).status_code == 201
    aged_id = await seed_old_replay(ctx, 'fund-live', 'bad-archive')
    async with ctx.factory.begin() as session:
        session.add(Receipt(key_digest=idempotency_key_digest(user_id=ctx.users[0].id, scope='sandbox_top_up.create', key='bad-archive'),
                            payload_hash='0' * 64, resource_id=uuid4()))
    with pytest.raises(RuntimeError, match='archive does not match'):
        await clean(ctx.factory)
    async with ctx.factory() as session:
        assert await session.get(Idempotency, aged_id) is not None


async def test_database_rolls_back_duplicate_post_from_receipt_unaware_claim(ctx, monkeypatch):
    assert (await top_up(ctx, key='fund-live')).status_code == 201
    await seed_old_replay(ctx, 'fund-live', 'old-client-key')
    await clean(ctx.factory)
    original_claim = SqlAlchemyIdempotencyRepository.claim

    async def receipt_unaware_claim(self, **kwargs):
        # Emulate a legacy claim that inserts a new reservation and ignores the
        # archived result. The database must reject the entire second posting.
        await original_claim(self, **kwargs)
        return None

    monkeypatch.setattr(SqlAlchemyIdempotencyRepository, 'claim', receipt_unaware_claim)
    with pytest.raises(IntegrityError, match='Permanent replay result cannot change'):
        await top_up(ctx, key='old-client-key')
    assert (await balance(ctx))['posted_minor'] == '50000'
    assert await count(ctx.factory, Journal) == 1
    assert await count(ctx.factory, Idempotency) == 1

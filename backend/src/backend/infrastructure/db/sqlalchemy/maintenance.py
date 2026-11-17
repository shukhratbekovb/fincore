from dataclasses import asdict
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.maintenance.dtos import CleanupExpiredDataCommand, CleanupReport
from backend.application.maintenance.interfaces.store import IMaintenanceStore
from backend.infrastructure.db.sqlalchemy.models import (
    SqlAlchemyIdempotencyModel as Idempotency,
    SqlAlchemyIdempotencyReceiptModel as Receipt,
    SqlAlchemyOutboxModel as Outbox,
    SqlAlchemyRefreshTokenModel as RefreshToken,
    SqlAlchemySessionModel as Session,
    SqlAlchemyVerificationChallengeModel as Challenge,
)
from backend.infrastructure.security.idempotency import idempotency_key_digest


class SqlAlchemyMaintenanceStore(IMaintenanceStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def cleanup(self, cmd: CleanupExpiredDataCommand) -> CleanupReport:
        async with self._session_factory.begin() as session:
            # Database time also governs the idempotency DELETE guard. An API
            # host's clock must never authorize an early deletion.
            now = await session.scalar(select(func.statement_timestamp()))
            if cmd.dry_run:
                return await self._preview(session, cmd, now)
        counts = asdict(CleanupReport(as_of=now, dry_run=False))
        for kind in ("sessions", "verification_challenges", "outbox_messages", "idempotency_records"):
            for batch in range(cmd.max_batches):
                # Each batch owns its session/transaction. Slow refresh, confirm
                # and money operations are skipped instead of waited on.
                async with self._session_factory.begin() as session:
                    model, condition, order = self._selection(kind, cmd, now)
                    result = await session.execute(
                        select(model).where(condition).order_by(order, model.id)
                        .limit(cmd.batch_size).with_for_update(skip_locked=True)
                    )
                    records = result.scalars().all()
                    ids = [record.id for record in records]
                    if kind == "sessions" and ids:
                        deleted = await session.execute(delete(RefreshToken).where(RefreshToken.session_id.in_(ids)))
                        counts["refresh_tokens"] += deleted.rowcount
                    if kind == "idempotency_records" and records:
                        counts["receipts_created"] += await self._archive_receipts(session, records)
                    if ids:
                        await session.execute(delete(model).where(model.id.in_(ids)))
                counts[kind] += len(ids)
                if len(ids) < cmd.batch_size:
                    break
                if batch + 1 == cmd.max_batches:
                    counts["batch_limit_reached"] = True
        return CleanupReport(**counts)

    @staticmethod
    def _selection(kind: str, cmd: CleanupExpiredDataCommand, now: datetime):
        policy = cmd.policy
        if kind == "sessions":
            cutoff = now - policy.session_retention
            return Session, or_(Session.expires_at <= cutoff, Session.revoked_at <= cutoff), Session.expires_at
        if kind == "verification_challenges":
            return Challenge, Challenge.expires_at <= now - policy.challenge_retention, Challenge.expires_at
        if kind == "outbox_messages":
            return Outbox, and_(
                Outbox.status.in_(("sent", "failed", "expired")),
                Outbox.completed_at <= now - policy.outbox_retention,
            ), Outbox.completed_at
        return Idempotency, and_(
            Idempotency.expires_at <= now,
            Idempotency.created_at <= now - policy.idempotency_retention,
            Idempotency.resource_id.is_not(None),
        ), Idempotency.expires_at

    async def _preview(self, session: AsyncSession, cmd: CleanupExpiredDataCommand, now: datetime) -> CleanupReport:
        # No locks and no writes; all counts use one statement snapshot.
        queries = {}
        for kind in ("sessions", "verification_challenges", "outbox_messages", "idempotency_records"):
            model, condition, _ = self._selection(kind, cmd, now)
            queries[kind] = select(func.count()).select_from(model).where(condition).scalar_subquery().label(kind)
        _, session_condition, _ = self._selection("sessions", cmd, now)
        queries["refresh_tokens"] = select(func.count()).select_from(RefreshToken).where(
            RefreshToken.session_id.in_(select(Session.id).where(session_condition))
        ).scalar_subquery().label("refresh_tokens")
        row = (await session.execute(select(*queries.values()))).mappings().one()
        return CleanupReport(as_of=now, dry_run=True, **dict(row))

    @staticmethod
    async def _archive_receipts(session: AsyncSession, records: list[Idempotency]) -> int:
        values = [dict(
            key_digest=idempotency_key_digest(user_id=record.user_id, scope=record.scope, key=record.key),
            payload_hash=record.payload_hash, resource_id=record.resource_id,
        ) for record in records]
        result = await session.execute(
            insert(Receipt).values(values).on_conflict_do_nothing(index_elements=[Receipt.key_digest])
            .returning(Receipt.key_digest)
        )
        created = len(result.scalars().all())
        receipts = (await session.execute(select(Receipt).where(
            Receipt.key_digest.in_([value["key_digest"] for value in values])
        ))).scalars().all()
        by_digest = {receipt.key_digest: receipt for receipt in receipts}
        for value in values:
            receipt = by_digest[value["key_digest"]]
            if receipt.payload_hash != value["payload_hash"] or receipt.resource_id != value["resource_id"]:
                raise RuntimeError("Idempotency archive does not match the completed result")
        return created

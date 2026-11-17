from datetime import timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.outbox.dtos.delivery import OutboxDelivery
from backend.application.outbox.interfaces.queue import IOutboxQueue
from backend.application.share.errors import UnsupportedOutboxMessageError
from backend.domain.share.errors import DomainError
from backend.infrastructure.db.sqlalchemy.models.outbox import SqlAlchemyOutboxModel
from backend.infrastructure.db.sqlalchemy.repository.outbox import _to_entity as _to_message


def _to_entity(model: SqlAlchemyOutboxModel) -> OutboxDelivery:
    return OutboxDelivery(
        id=model.id, lock_token=model.lock_token, attempts=model.attempts,
        message=_to_message(model),
    )


class SqlAlchemyOutboxQueue(IOutboxQueue):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def claim(self, *, limit: int, lease: timedelta) -> list[OutboxDelivery]:
        async with self._session_factory.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            stmt = select(SqlAlchemyOutboxModel).where(or_(
                and_(SqlAlchemyOutboxModel.status == "pending", SqlAlchemyOutboxModel.next_attempt_at <= now),
                and_(SqlAlchemyOutboxModel.status == "processing", SqlAlchemyOutboxModel.locked_until <= now),
            )).order_by(SqlAlchemyOutboxModel.created_at, SqlAlchemyOutboxModel.id).limit(limit).with_for_update(skip_locked=True)
            result = await session.execute(stmt)
            now = await session.scalar(select(func.clock_timestamp()))
            deliveries = []
            for model in result.scalars():
                model.status = "processing"
                model.attempts += 1
                model.lock_token = uuid4()
                model.locked_until = now + lease
                try:
                    deliveries.append(_to_entity(model))
                except (UnsupportedOutboxMessageError, DomainError, ValueError, TypeError, KeyError, OverflowError):
                    model.status = "failed"
                    model.payload = None
                    model.lock_token = None
                    model.locked_until = None
                    model.completed_at = now
                    model.last_error = "invalid_message"
            return deliveries

    async def finish(
            self, delivery: OutboxDelivery, *, status: Literal["sent", "failed", "expired"],
            error_code: str | None = None,
    ) -> bool:
        async with self._session_factory.begin() as session:
            stmt = update(SqlAlchemyOutboxModel).where(
                SqlAlchemyOutboxModel.id == delivery.id,
                SqlAlchemyOutboxModel.status == "processing",
                SqlAlchemyOutboxModel.lock_token == delivery.lock_token,
                SqlAlchemyOutboxModel.locked_until > func.clock_timestamp(),
            ).values(
                status=status, payload=None, lock_token=None, locked_until=None,
                completed_at=func.clock_timestamp(), last_error=error_code,
            ).returning(SqlAlchemyOutboxModel.id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def retry(self, delivery: OutboxDelivery, *, delay: timedelta, error_code: str) -> bool:
        async with self._session_factory.begin() as session:
            stmt = update(SqlAlchemyOutboxModel).where(
                SqlAlchemyOutboxModel.id == delivery.id,
                SqlAlchemyOutboxModel.status == "processing",
                SqlAlchemyOutboxModel.lock_token == delivery.lock_token,
                SqlAlchemyOutboxModel.locked_until > func.clock_timestamp(),
            ).values(
                status="pending", lock_token=None, locked_until=None,
                next_attempt_at=func.clock_timestamp() + delay, last_error=error_code,
            ).returning(SqlAlchemyOutboxModel.id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

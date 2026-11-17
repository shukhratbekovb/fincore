from uuid import UUID, uuid4

from sqlalchemy import select, update, text, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from backend.application.idempotency.dtos import IdempotencyRecord
from backend.application.idempotency.errors import IdempotencyInProgressError
from backend.application.idempotency.interfaces.repository import IIdempotencyRepository
from backend.application.share.errors import EntityNotFoundError
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyIdempotencyModel, SqlAlchemyIdempotencyReceiptModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository
from backend.infrastructure.security.idempotency import idempotency_key_digest


def _to_entity(model: SqlAlchemyIdempotencyModel) -> IdempotencyRecord:
    return IdempotencyRecord(payload_hash=model.payload_hash, resource_id=model.resource_id)


def _to_model(*, user_id: UUID, scope: str, key: str, payload_hash: str) -> SqlAlchemyIdempotencyModel:
    return SqlAlchemyIdempotencyModel(id=uuid4(), user_id=user_id, scope=scope, key=key, payload_hash=payload_hash)


class SqlAlchemyIdempotencyRepository(IIdempotencyRepository, SqlAlchemyBaseRepository):
    async def claim(self, *, user_id: UUID, scope: str, key: str, payload_hash: str) -> IdempotencyRecord | None:
        model = _to_model(user_id=user_id, scope=scope, key=key, payload_hash=payload_hash)
        previous_timeout = await self.session.scalar(text("SHOW lock_timeout"))
        try:
            async with self.session.begin_nested():
                await self.session.execute(select(func.set_config('lock_timeout', '2000ms', True)))
                stmt = insert(SqlAlchemyIdempotencyModel).values(
                    id=model.id, user_id=model.user_id, scope=model.scope, key=model.key, payload_hash=model.payload_hash,
                ).on_conflict_do_nothing(constraint="uq_idempotency_scope_key").returning(SqlAlchemyIdempotencyModel.id)
                result = await self.session.execute(stmt)
                inserted = result.scalar_one_or_none() is not None
                # Check AFTER the insert/conflict wait: cleanup may have archived
                # and deleted the original row while this INSERT was waiting.
                receipt = await self.session.get(
                    SqlAlchemyIdempotencyReceiptModel,
                    idempotency_key_digest(user_id=user_id, scope=scope, key=key),
                    populate_existing=True,
                )
                if receipt is not None:
                    record = IdempotencyRecord(payload_hash=receipt.payload_hash, resource_id=receipt.resource_id)
                elif inserted:
                    record = None
                else:
                    stmt = select(SqlAlchemyIdempotencyModel).where(
                        SqlAlchemyIdempotencyModel.user_id == user_id,
                        SqlAlchemyIdempotencyModel.scope == scope,
                        SqlAlchemyIdempotencyModel.key == key,
                    ).with_for_update().execution_options(populate_existing=True)
                    result = await self.session.execute(stmt)
                    existing = result.scalar_one_or_none()
                    if existing is None:
                        raise IdempotencyInProgressError()
                    record = _to_entity(existing)
                await self.session.execute(select(func.set_config('lock_timeout', previous_timeout, True)))
                return record
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
                raise IdempotencyInProgressError() from exc
            raise

    async def complete(self, *, user_id: UUID, scope: str, key: str, payload_hash: str, resource_id: UUID) -> None:
        stmt = update(SqlAlchemyIdempotencyModel).where(
            SqlAlchemyIdempotencyModel.user_id == user_id, SqlAlchemyIdempotencyModel.scope == scope,
            SqlAlchemyIdempotencyModel.key == key, SqlAlchemyIdempotencyModel.payload_hash == payload_hash,
            SqlAlchemyIdempotencyModel.resource_id.is_(None),
        ).values(resource_id=resource_id).returning(SqlAlchemyIdempotencyModel.id)
        result = await self.session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise EntityNotFoundError("Idempotency reservation not found")

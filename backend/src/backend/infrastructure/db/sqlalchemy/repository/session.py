from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update

from backend.application.share.errors import EntityNotFoundError
from backend.application.session.interfaces.repository import ISessionRepository
from backend.domain.session.entities import Session
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemySessionModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_entity(
        model: SqlAlchemySessionModel
) -> Session:
    return Session(
        id=model.id,
        user_id=model.user_id,
        expires_at=model.expires_at,
        ip_address=model.ip_address,
        user_agent=model.user_agent,
        last_used_at=model.last_used_at,
        last_ip_address=model.last_ip_address,
        last_user_agent=model.last_user_agent,
        revoked_at=model.revoked_at,
        created_at=model.created_at,
        updated_at=model.updated_at
    )


def _to_model(
        entity: Session
) -> SqlAlchemySessionModel:
    return SqlAlchemySessionModel(
        id=entity.id,
        user_id=entity.user_id,
        expires_at=entity.expires_at,
        ip_address=entity.ip_address,
        user_agent=entity.user_agent,
        last_used_at=entity.last_used_at,
        last_ip_address=entity.last_ip_address,
        last_user_agent=entity.last_user_agent,
        revoked_at=entity.revoked_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at
    )


class SqlAlchemySessionRepository(
    ISessionRepository,
    SqlAlchemyBaseRepository
):

    async def add(self, session: Session) -> None:
        model = _to_model(session)
        self.session.add(model)
        await self.session.flush()

    async def get_by_id(self, session_id: UUID) -> Session | None:
        stmt = select(SqlAlchemySessionModel).where(SqlAlchemySessionModel.id == session_id)
        result = await self.session.execute(stmt)
        session = result.scalar_one_or_none()
        return _to_entity(session) if session else None

    async def get_by_id_for_update(self, session_id: UUID) -> Session | None:
        stmt = (
            select(SqlAlchemySessionModel)
            .where(SqlAlchemySessionModel.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        session = result.scalar_one_or_none()
        return _to_entity(session) if session else None

    async def revoke_all_by_user_id(self, user_id: UUID, *, now: datetime) -> None:
        stmt = (
            update(SqlAlchemySessionModel)
            .where(
                SqlAlchemySessionModel.user_id == user_id,
                SqlAlchemySessionModel.revoked_at.is_(None)
            )
            .values(
                revoked_at=now,
                updated_at=now,
            )
        )
        await self.session.execute(stmt)

    async def save(self, session: Session) -> None:
        stmt = (
            update(SqlAlchemySessionModel)
            .where(SqlAlchemySessionModel.id == session.id)
            .values(
                revoked_at=session.revoked_at,
                last_used_at=session.last_used_at,
                last_ip_address=session.last_ip_address,
                last_user_agent=session.last_user_agent,
                updated_at=session.updated_at,
            )
            .returning(SqlAlchemySessionModel.id)
        )

        result = await self.session.execute(stmt)

        if result.scalar_one_or_none() is None:
            raise EntityNotFoundError("sessions record not found")

    async def get_active_by_user_id(self, user_id: UUID, *, now: datetime) -> list[Session]:
        stmt = (
            select(SqlAlchemySessionModel)
        ).where(
            SqlAlchemySessionModel.user_id == user_id,
            SqlAlchemySessionModel.revoked_at.is_(None),
            SqlAlchemySessionModel.expires_at > now
        ).order_by(
            SqlAlchemySessionModel.created_at.desc(),
            SqlAlchemySessionModel.id.desc(),
        )
        result = await self.session.execute(stmt)
        sessions = result.scalars().all()
        return [_to_entity(session) for session in sessions]

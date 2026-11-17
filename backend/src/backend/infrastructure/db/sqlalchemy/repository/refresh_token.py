from uuid import UUID

from sqlalchemy import select, update

from backend.application.share.errors import EntityNotFoundError
from backend.application.session.interfaces.repository import IRefreshTokenRepository
from backend.domain.session.entities import RefreshToken
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyRefreshTokenModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_entity(
        model: SqlAlchemyRefreshTokenModel
) -> RefreshToken:
    return RefreshToken(
        id=model.id,
        session_id=model.session_id,
        token_hash=model.token_hash,
        expires_at=model.expires_at,
        used_at=model.used_at,
        replaced_by_id=model.replaced_by_id
    )


def _to_model(
        entity: RefreshToken
) -> SqlAlchemyRefreshTokenModel:
    return SqlAlchemyRefreshTokenModel(
        id=entity.id,
        session_id=entity.session_id,
        token_hash=entity.token_hash,
        expires_at=entity.expires_at,
        used_at=entity.used_at,
        replaced_by_id=entity.replaced_by_id
    )


class SqlAlchemyRefreshTokenRepository(
    IRefreshTokenRepository,
    SqlAlchemyBaseRepository
):

    async def add(self, token: RefreshToken) -> None:
        model = _to_model(token)
        self.session.add(model)
        await self.session.flush()

    async def get_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(SqlAlchemyRefreshTokenModel).where(SqlAlchemyRefreshTokenModel.token_hash == token_hash)
        result = await self.session.execute(stmt)
        token = result.scalar_one_or_none()
        return _to_entity(token) if token else None

    async def get_by_id_for_update(self, token_id: UUID) -> RefreshToken | None:
        stmt = (
            select(SqlAlchemyRefreshTokenModel)
            .where(SqlAlchemyRefreshTokenModel.id == token_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        token = result.scalar_one_or_none()
        return _to_entity(token) if token else None

    async def save(self, token: RefreshToken) -> None:
        stmt = (
            update(SqlAlchemyRefreshTokenModel)
            .where(SqlAlchemyRefreshTokenModel.id == token.id)
            .values(
                used_at=token.used_at,
                replaced_by_id=token.replaced_by_id,
            )
            .returning(SqlAlchemyRefreshTokenModel.id)
        )

        result = await self.session.execute(stmt)

        if result.scalar_one_or_none() is None:
            raise EntityNotFoundError("refresh_tokens record not found")

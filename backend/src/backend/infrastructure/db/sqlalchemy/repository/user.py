from uuid import UUID

from sqlalchemy import select, update

from backend.application.user.errors import UserNotFoundError
from backend.application.user.interfaces.repository import IUserRepository
from backend.domain.user.entities import User
from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.value_objects import Email, Username, HashedPassword
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyUserModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_entity(
        model: SqlAlchemyUserModel
) -> User:
    return User(
        id=model.id,
        email=Email(model.email),
        username=Username(model.username),
        password_hash=HashedPassword(model.password_hash) if model.password_hash is not None else None,
        status=UserStatusEnum(model.status),
        last_login_at=model.last_login_at,
        created_at=model.created_at,
        updated_at=model.updated_at
    )


def _to_model(
        entity: User
) -> SqlAlchemyUserModel:
    return SqlAlchemyUserModel(
        id=entity.id,
        email=entity.email.value,
        username=entity.username.value,
        password_hash=entity.password_hash.value if entity.password_hash is not None else None,
        status=entity.status.value,
        last_login_at=entity.last_login_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at
    )


class SqlAlchemyUserRepository(
    IUserRepository,
    SqlAlchemyBaseRepository
):

    async def add(self, user: User) -> None:
        model = _to_model(user)
        self.session.add(model)
        await self.session.flush()

    async def get_by_email(self, email: Email) -> User | None:
        stmt = select(SqlAlchemyUserModel).where(SqlAlchemyUserModel.email == email.value)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        return _to_entity(user) if user else None

    async def get_by_username(self, username: Username) -> User | None:
        stmt = select(SqlAlchemyUserModel).where(SqlAlchemyUserModel.username == username.value)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        return _to_entity(user) if user else None

    async def get_by_id(self, user_id: UUID) -> User | None:
        stmt = select(SqlAlchemyUserModel).where(SqlAlchemyUserModel.id == user_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        return _to_entity(user) if user else None

    async def get_by_id_for_update(self, user_id: UUID) -> User | None:
        stmt = (
            select(SqlAlchemyUserModel)
            .where(SqlAlchemyUserModel.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        return _to_entity(user) if user else None

    async def save(self, user: User) -> None:
        stmt = (
            update(SqlAlchemyUserModel)
            .where(SqlAlchemyUserModel.id == user.id)
            .values(
                username=user.username.value,
                email=user.email.value,
                password_hash=(
                    user.password_hash.value
                    if user.password_hash is not None
                    else None
                ),
                status=user.status.value,
                last_login_at=user.last_login_at,
                updated_at=user.updated_at,
            )
            .returning(SqlAlchemyUserModel.id)
        )

        result = await self.session.execute(stmt)

        if result.scalar_one_or_none() is None:
            raise UserNotFoundError()

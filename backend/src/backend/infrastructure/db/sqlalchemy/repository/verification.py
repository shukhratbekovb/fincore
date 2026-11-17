from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update

from backend.application.share.errors import EntityNotFoundError
from backend.application.verification.interfaces.repository import IVerificationChallengeRepository
from backend.domain.verification.entities import VerificationChallenge
from backend.domain.verification.enums import VerificationPurpose
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemyVerificationChallengeModel
from backend.infrastructure.db.sqlalchemy.repository.base import SqlAlchemyBaseRepository


def _to_entity(
        model: SqlAlchemyVerificationChallengeModel
) -> VerificationChallenge:
    return VerificationChallenge(
        id=model.id,
        user_id=model.user_id,
        purpose=VerificationPurpose(model.purpose),
        token_hash=model.token_hash,
        expires_at=model.expires_at,
        used_at=model.used_at
    )


def _to_model(
        entity: VerificationChallenge
) -> SqlAlchemyVerificationChallengeModel:
    return SqlAlchemyVerificationChallengeModel(
        id=entity.id,
        user_id=entity.user_id,
        purpose=entity.purpose.value,
        token_hash=entity.token_hash,
        expires_at=entity.expires_at,
        used_at=entity.used_at
    )


class SqlAlchemyVerificationChallengeRepository(
    IVerificationChallengeRepository,
    SqlAlchemyBaseRepository
):

    async def add(self, challenge: VerificationChallenge) -> None:
        model = _to_model(challenge)
        self.session.add(model)
        await self.session.flush()

    async def get_by_token_hash_for_update(self, token_hash: str) -> VerificationChallenge | None:
        stmt = (
            select(SqlAlchemyVerificationChallengeModel)
            .where(SqlAlchemyVerificationChallengeModel.token_hash == token_hash)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        challenge = result.scalar_one_or_none()
        return _to_entity(challenge) if challenge else None

    async def get_by_token_hash(self, token_hash: str) -> VerificationChallenge | None:
        stmt = (
            select(SqlAlchemyVerificationChallengeModel)
            .where(SqlAlchemyVerificationChallengeModel.token_hash == token_hash)
        )
        result = await self.session.execute(stmt)
        challenge = result.scalar_one_or_none()
        return _to_entity(challenge) if challenge else None

    async def invalidate_unused_by_user_id(
            self, user_id: UUID, *, purpose: VerificationPurpose, now: datetime,
    ) -> None:
        stmt = (
            update(SqlAlchemyVerificationChallengeModel)
            .where(
                SqlAlchemyVerificationChallengeModel.user_id == user_id,
                SqlAlchemyVerificationChallengeModel.purpose == purpose.value,
                SqlAlchemyVerificationChallengeModel.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await self.session.execute(stmt)

    async def save(self, challenge: VerificationChallenge) -> None:
        stmt = (
            update(SqlAlchemyVerificationChallengeModel)
            .where(SqlAlchemyVerificationChallengeModel.id == challenge.id)
            .values(
                used_at=challenge.used_at,
            )
            .returning(SqlAlchemyVerificationChallengeModel.id)
        )

        result = await self.session.execute(stmt)

        if result.scalar_one_or_none() is None:
            raise EntityNotFoundError("verification_challenges record not found")

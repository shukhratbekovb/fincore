from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin


class SqlAlchemyVerificationChallengeModel(SqlAlchemyIdentityMixin, SqlAlchemyBaseModel):
    __tablename__ = "verification_challenges"
    __table_args__ = (
        Index('ix_verification_cleanup_expires', 'expires_at', 'id'),
        UniqueConstraint("token_hash", name="uq_verification_challenges_hash"),
        CheckConstraint("purpose IN ('registration', 'password_reset')", name="ck_verification_purpose"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]

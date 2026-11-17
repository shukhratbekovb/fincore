from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin, SqlAlchemyTimeActionMixin


class SqlAlchemySessionModel(SqlAlchemyIdentityMixin, SqlAlchemyTimeActionMixin, SqlAlchemyBaseModel):
    __tablename__ = "sessions"
    __table_args__ = (
        Index('ix_sessions_cleanup_expires', 'expires_at', 'id'),
        Index('ix_sessions_cleanup_revoked', 'revoked_at', 'id'),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime]
    ip_address: Mapped[str] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    last_used_at: Mapped[datetime | None]
    last_ip_address: Mapped[str | None] = mapped_column(String(45))
    last_user_agent: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None]


class SqlAlchemyRefreshTokenModel(SqlAlchemyIdentityMixin, SqlAlchemyBaseModel):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
        UniqueConstraint("id", "session_id", name="uq_refresh_tokens_id_session"),
        ForeignKeyConstraint(
            ["replaced_by_id", "session_id"], ["refresh_tokens.id", "refresh_tokens.session_id"],
            name="fk_refresh_tokens_replacement_session",
        ),
        CheckConstraint("(used_at IS NULL) = (replaced_by_id IS NULL)", name="ck_refresh_tokens_rotation"),
    )

    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"), index=True)
    token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    replaced_by_id: Mapped[UUID | None]

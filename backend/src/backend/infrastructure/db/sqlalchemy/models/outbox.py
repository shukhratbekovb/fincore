from datetime import datetime, timezone

from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin


class SqlAlchemyOutboxModel(SqlAlchemyIdentityMixin, SqlAlchemyBaseModel):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint("status IN ('pending','processing','sent','failed','expired')", name="ck_outbox_status"),
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        CheckConstraint("(status = 'processing' AND lock_token IS NOT NULL AND locked_until IS NOT NULL) OR (status <> 'processing' AND lock_token IS NULL AND locked_until IS NULL)", name="ck_outbox_lease"),
        CheckConstraint("(status IN ('pending','processing')) = (payload IS NOT NULL)", name="ck_outbox_payload"),
        Index("ix_outbox_pending", "next_attempt_at", "created_at", postgresql_where=text("status = 'pending'")),
        Index("ix_outbox_processing", "locked_until", postgresql_where=text("status = 'processing'")),
        Index("ix_outbox_cleanup_completed", "completed_at", "id", postgresql_where=text("status IN ('sent','failed','expired')")),
    )

    message_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(server_default=func.now())
    locked_until: Mapped[datetime | None]
    lock_token: Mapped[UUID | None]
    completed_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(String(64))

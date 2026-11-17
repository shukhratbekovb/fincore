from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyIdentityMixin


class SqlAlchemyIdempotencyModel(SqlAlchemyIdentityMixin, SqlAlchemyBaseModel):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        Index('ix_idempotency_cleanup_expires', 'expires_at', 'id'),
        UniqueConstraint("user_id", "scope", "key", name="uq_idempotency_scope_key"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="ck_idempotency_hash"),
        CheckConstraint("expires_at >= created_at + interval '24 hours'", name="ck_idempotency_retention"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(String(80))
    key: Mapped[str] = mapped_column(String(255))
    payload_hash: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(server_default=text("now() + interval '24 hours'"))


class SqlAlchemyIdempotencyReceiptModel(SqlAlchemyBaseModel):
    __tablename__ = "idempotency_receipts"
    __table_args__ = (
        CheckConstraint("key_digest ~ '^[0-9a-f]{64}$'", name="ck_receipt_key_digest"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="ck_receipt_payload_hash"),
    )
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID]
    archived_at: Mapped[datetime] = mapped_column(server_default=func.now())

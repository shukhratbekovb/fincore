"""Lease-based outbox delivery and secret payload cleanup."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261105_02"
down_revision = "20261104_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("outbox_messages", "payload", existing_type=postgresql.JSONB(), nullable=True)
    op.add_column("outbox_messages", sa.Column("status", sa.String(20), nullable=False, server_default="pending"))
    op.add_column("outbox_messages", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("outbox_messages", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("outbox_messages", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox_messages", sa.Column("lock_token", sa.Uuid(), nullable=True))
    op.add_column("outbox_messages", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox_messages", sa.Column("last_error", sa.String(64), nullable=True))
    op.create_check_constraint("ck_outbox_status", "outbox_messages", "status IN ('pending','processing','sent','failed','expired')")
    op.create_check_constraint("ck_outbox_attempts", "outbox_messages", "attempts >= 0")
    op.create_check_constraint("ck_outbox_lease", "outbox_messages", "(status = 'processing' AND lock_token IS NOT NULL AND locked_until IS NOT NULL) OR (status <> 'processing' AND lock_token IS NULL AND locked_until IS NULL)")
    op.create_check_constraint("ck_outbox_payload", "outbox_messages", "(status IN ('pending','processing')) = (payload IS NOT NULL)")
    op.create_index("ix_outbox_pending", "outbox_messages", ["next_attempt_at", "created_at"], postgresql_where=sa.text("status = 'pending'"))
    op.create_index("ix_outbox_processing", "outbox_messages", ["locked_until"], postgresql_where=sa.text("status = 'processing'"))


def downgrade() -> None:
    # Completed rows have no payload and cannot be represented in the old schema.
    op.execute("DELETE FROM outbox_messages WHERE payload IS NULL")
    op.drop_index("ix_outbox_processing", table_name="outbox_messages")
    op.drop_index("ix_outbox_pending", table_name="outbox_messages")
    for constraint in ("ck_outbox_payload", "ck_outbox_lease", "ck_outbox_attempts", "ck_outbox_status"):
        op.drop_constraint(constraint, "outbox_messages", type_="check")
    for column in ("last_error", "completed_at", "lock_token", "locked_until", "next_attempt_at", "attempts", "status"):
        op.drop_column("outbox_messages", column)
    op.alter_column("outbox_messages", "payload", existing_type=postgresql.JSONB(), nullable=False)

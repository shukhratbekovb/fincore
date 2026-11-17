"""Shared password reset request limits."""
from alembic import op
import sqlalchemy as sa

revision = "20261105_03"
down_revision = "20261105_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts > 0", name="ck_auth_rate_limit_attempts"),
    )
    op.create_index("ix_auth_rate_limit_expires", "auth_rate_limits", ["expires_at"])


def downgrade() -> None:
    op.drop_table("auth_rate_limits")

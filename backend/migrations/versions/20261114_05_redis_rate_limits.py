"""Retire PostgreSQL request counters after switching the API to Redis."""
from alembic import op
import sqlalchemy as sa

revision = '20261114_05'
down_revision = '20261112_04'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Counters are temporary; switching stores starts fresh request windows.
    op.drop_table('auth_rate_limits')


def downgrade() -> None:
    op.create_table(
        'auth_rate_limits',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('attempts > 0', name='ck_auth_rate_limit_attempts'),
    )
    op.create_index('ix_auth_rate_limit_expires', 'auth_rate_limits', ['expires_at'])

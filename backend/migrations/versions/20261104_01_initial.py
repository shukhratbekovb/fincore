"""Initial users, sessions, verification, wallets, accounting and outbox schema."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261104_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('outbox_messages',
    sa.Column('message_type', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('username', sa.String(length=256), nullable=False),
    sa.Column('email', sa.String(length=512), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('sessions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ip_address', sa.String(length=45), nullable=False),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_ip_address', sa.String(length=45), nullable=True),
    sa.Column('last_user_agent', sa.Text(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('verification_challenges',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('purpose', sa.String(length=30), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("purpose IN ('registration', 'password_reset')", name='ck_verification_purpose'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash', name='uq_verification_challenges_hash')
    )
    op.create_index(op.f('ix_verification_challenges_user_id'), 'verification_challenges', ['user_id'], unique=False)
    op.create_table('wallets',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('number', sa.String(length=20), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("currency IN ('USD','EUR','JPY','CHF','GBP','UZS','CAD','RUB')", name='ck_wallets_currency'),
    sa.CheckConstraint("number ~ '^[0-9]{20}$'", name='ck_wallets_number'),
    sa.CheckConstraint("status IN ('active', 'frozen', 'closed')", name='ck_wallets_status'),
    sa.CheckConstraint('length(trim(name)) BETWEEN 1 AND 64', name='ck_wallets_name'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'currency', name='uq_wallets_id_currency'),
    sa.UniqueConstraint('number', name='uq_wallets_number')
    )
    op.create_index(op.f('ix_wallets_user_id'), 'wallets', ['user_id'], unique=False)
    op.create_table('ledger_accounts',
    sa.Column('code', sa.String(length=80), nullable=False),
    sa.Column('account_type', sa.String(length=20), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('wallet_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("(wallet_id IS NOT NULL AND account_type = 'liability' AND code = 'WALLET:' || CAST(wallet_id AS VARCHAR) || ':' || currency) OR (wallet_id IS NULL AND account_type = 'asset' AND code = 'SYS:SIM_FUNDING:' || currency)", name='ck_ledger_accounts_purpose'),
    sa.CheckConstraint("currency IN ('USD','EUR','JPY','CHF','GBP','UZS','CAD','RUB')", name='ck_ledger_accounts_currency'),
    sa.CheckConstraint("status IN ('active', 'closed')", name='ck_ledger_accounts_status'),
    sa.ForeignKeyConstraint(['wallet_id', 'currency'], ['wallets.id', 'wallets.currency'], name='fk_ledger_accounts_wallet_currency'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='uq_ledger_accounts_code'),
    sa.UniqueConstraint('wallet_id', name='uq_ledger_accounts_wallet')
    )
    op.create_table('refresh_tokens',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('(used_at IS NULL) = (replaced_by_id IS NULL)', name='ck_refresh_tokens_rotation'),
    sa.ForeignKeyConstraint(['replaced_by_id', 'session_id'], ['refresh_tokens.id', 'refresh_tokens.session_id'], name='fk_refresh_tokens_replacement_session'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'session_id', name='uq_refresh_tokens_id_session'),
    sa.UniqueConstraint('token_hash', name='uq_refresh_tokens_hash')
    )
    op.create_index(op.f('ix_refresh_tokens_session_id'), 'refresh_tokens', ['session_id'], unique=False)
    op.create_table('wallet_balances',
    sa.Column('wallet_id', sa.Uuid(), nullable=False),
    sa.Column('posted_minor', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('version', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('posted_minor >= 0', name='ck_wallet_balances_nonnegative'),
    sa.CheckConstraint('version >= 0', name='ck_wallet_balances_version'),
    sa.ForeignKeyConstraint(['wallet_id'], ['wallets.id'], ),
    sa.PrimaryKeyConstraint('wallet_id')
    )


def downgrade() -> None:
    op.drop_table('wallet_balances')
    op.drop_index(op.f('ix_refresh_tokens_session_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_table('ledger_accounts')
    op.drop_index(op.f('ix_wallets_user_id'), table_name='wallets')
    op.drop_table('wallets')
    op.drop_index(op.f('ix_verification_challenges_user_id'), table_name='verification_challenges')
    op.drop_table('verification_challenges')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_table('outbox_messages')

"""Service data retention indexes and permanent compact money replay receipts."""
from alembic import op
import sqlalchemy as sa

revision = '20261115_06'
down_revision = '20261114_05'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'idempotency_receipts',
        sa.Column('key_digest', sa.String(64), primary_key=True),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('resource_id', sa.Uuid(), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("key_digest ~ '^[0-9a-f]{64}$'", name='ck_receipt_key_digest'),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name='ck_receipt_payload_hash'),
    )
    op.create_index('ix_sessions_cleanup_expires', 'sessions', ['expires_at', 'id'])
    op.create_index('ix_sessions_cleanup_revoked', 'sessions', ['revoked_at', 'id'])
    op.create_index('ix_verification_cleanup_expires', 'verification_challenges', ['expires_at', 'id'])
    op.create_index('ix_idempotency_cleanup_expires', 'idempotency_records', ['expires_at', 'id'])
    op.create_index('ix_outbox_cleanup_completed', 'outbox_messages', ['completed_at', 'id'],
                    postgresql_where=sa.text("status IN ('sent','failed','expired')"))
    op.execute('CREATE TRIGGER immutable_receipt BEFORE UPDATE OR DELETE ON idempotency_receipts FOR EACH ROW EXECUTE FUNCTION fincore_immutable()')
    op.execute('CREATE TRIGGER immutable_receipt_truncate BEFORE TRUNCATE ON idempotency_receipts FOR EACH STATEMENT EXECUTE FUNCTION fincore_immutable()')
    op.execute("""CREATE OR REPLACE FUNCTION fincore_idempotency_digest(actor uuid, operation text, client_key text)
    RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
      SELECT encode(sha256(convert_to('[' || to_json(actor::text)::text || ',' ||
        to_json(operation)::text || ',' || to_json(client_key)::text || ']', 'UTF8')), 'hex')
    $$""")
    op.execute("""CREATE OR REPLACE FUNCTION fincore_check_replay() RETURNS trigger
    LANGUAGE plpgsql SET search_path FROM CURRENT AS $$ DECLARE r record; valid boolean;
    BEGIN
      SELECT * INTO r FROM idempotency_records WHERE id=NEW.id;
      IF NOT FOUND THEN RETURN NULL; END IF;
      IF r.resource_id IS NULL THEN RAISE EXCEPTION 'Unfinished idempotency claim' USING ERRCODE='23514'; END IF;
      IF EXISTS (SELECT 1 FROM idempotency_receipts p
        WHERE p.key_digest=fincore_idempotency_digest(r.user_id,r.scope,r.key)
          AND (p.payload_hash<>r.payload_hash OR p.resource_id<>r.resource_id)) THEN
        RAISE EXCEPTION 'Permanent replay result cannot change' USING ERRCODE='23514';
      END IF;
      IF r.scope='transfer.create' THEN
        SELECT EXISTS(SELECT 1 FROM transfers t JOIN wallets w ON w.id=t.sender_wallet_id
          WHERE t.id=r.resource_id AND w.user_id=r.user_id AND t.status='completed') INTO valid;
      ELSIF r.scope='sandbox_top_up.create' THEN
        SELECT EXISTS(SELECT 1 FROM sandbox_top_ups t WHERE t.id=r.resource_id
          AND t.initiated_by_user_id=r.user_id AND t.status='completed') INTO valid;
      ELSE valid:=false; END IF;
      IF NOT valid THEN RAISE EXCEPTION 'Replay result does not match actor and operation' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    op.execute("""CREATE OR REPLACE FUNCTION fincore_replay_identity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='DELETE' THEN
        IF OLD.expires_at > statement_timestamp() THEN RAISE EXCEPTION 'Replay retention not elapsed' USING ERRCODE='23514'; END IF;
        IF NOT EXISTS (SELECT 1 FROM idempotency_receipts r
          WHERE r.key_digest=fincore_idempotency_digest(OLD.user_id, OLD.scope, OLD.key)
          AND r.payload_hash=OLD.payload_hash AND r.resource_id=OLD.resource_id) THEN
          RAISE EXCEPTION 'Permanent replay receipt required' USING ERRCODE='23514';
        END IF;
        RETURN OLD;
      END IF;
      IF OLD.resource_id IS NOT NULL OR ROW(NEW.id,NEW.user_id,NEW.scope,NEW.key,NEW.payload_hash,NEW.created_at,NEW.expires_at)
        IS DISTINCT FROM ROW(OLD.id,OLD.user_id,OLD.scope,OLD.key,OLD.payload_hash,OLD.created_at,OLD.expires_at) THEN
        RAISE EXCEPTION 'Replay identity and completed result are immutable' USING ERRCODE='23514';
      END IF; RETURN NEW;
    END $$""")


def downgrade() -> None:
    # Old application versions do not read receipts. Losing these would allow a
    # late replay to post money again; refuse downgrade after the first archive.
    op.execute('LOCK TABLE idempotency_records IN ACCESS EXCLUSIVE MODE')
    op.execute('LOCK TABLE idempotency_receipts IN ACCESS EXCLUSIVE MODE')
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM idempotency_receipts) THEN
        RAISE EXCEPTION 'Cannot downgrade with permanent replay receipts';
      END IF;
    END $$""")
    op.execute("""CREATE OR REPLACE FUNCTION fincore_replay_identity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='DELETE' THEN
        IF OLD.expires_at > statement_timestamp() THEN RAISE EXCEPTION 'Replay retention not elapsed' USING ERRCODE='23514'; END IF;
        RETURN OLD;
      END IF;
      IF OLD.resource_id IS NOT NULL OR ROW(NEW.id,NEW.user_id,NEW.scope,NEW.key,NEW.payload_hash,NEW.created_at,NEW.expires_at)
        IS DISTINCT FROM ROW(OLD.id,OLD.user_id,OLD.scope,OLD.key,OLD.payload_hash,OLD.created_at,OLD.expires_at) THEN
        RAISE EXCEPTION 'Replay identity and completed result are immutable' USING ERRCODE='23514';
      END IF; RETURN NEW;
    END $$""")
    op.execute("""CREATE OR REPLACE FUNCTION fincore_check_replay() RETURNS trigger
    LANGUAGE plpgsql SET search_path FROM CURRENT AS $$ DECLARE r record; valid boolean;
    BEGIN
      SELECT * INTO r FROM idempotency_records WHERE id=NEW.id;
      IF NOT FOUND THEN RETURN NULL; END IF;
      IF r.resource_id IS NULL THEN RAISE EXCEPTION 'Unfinished idempotency claim' USING ERRCODE='23514'; END IF;
      IF r.scope='transfer.create' THEN
        SELECT EXISTS(SELECT 1 FROM transfers t JOIN wallets w ON w.id=t.sender_wallet_id
          WHERE t.id=r.resource_id AND w.user_id=r.user_id AND t.status='completed') INTO valid;
      ELSIF r.scope='sandbox_top_up.create' THEN
        SELECT EXISTS(SELECT 1 FROM sandbox_top_ups t WHERE t.id=r.resource_id
          AND t.initiated_by_user_id=r.user_id AND t.status='completed') INTO valid;
      ELSE valid:=false; END IF;
      IF NOT valid THEN RAISE EXCEPTION 'Replay result does not match actor and operation' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    op.execute('DROP FUNCTION fincore_idempotency_digest(uuid, text, text)')
    op.drop_index('ix_outbox_cleanup_completed', table_name='outbox_messages')
    op.drop_index('ix_idempotency_cleanup_expires', table_name='idempotency_records')
    op.drop_index('ix_verification_cleanup_expires', table_name='verification_challenges')
    op.drop_index('ix_sessions_cleanup_revoked', table_name='sessions')
    op.drop_index('ix_sessions_cleanup_expires', table_name='sessions')
    op.drop_table('idempotency_receipts')

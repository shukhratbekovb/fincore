from sqlalchemy import event


LEDGER_GUARDS = [
    """CREATE OR REPLACE FUNCTION fincore_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      RAISE EXCEPTION 'Posted financial records are immutable' USING ERRCODE='23514';
    END $$""",
    """CREATE OR REPLACE FUNCTION fincore_validate_journal(jid uuid) RETURNS void
    LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
    DECLARE j record; o record; n bigint; deb numeric; cred numeric; good bigint;
    BEGIN
      SELECT * INTO j FROM ledger_transactions WHERE id=jid;
      IF NOT FOUND THEN RETURN; END IF;
      SELECT count(*), coalesce(sum(amount_minor) FILTER (WHERE side='debit'),0),
        coalesce(sum(amount_minor) FILTER (WHERE side='credit'),0)
        INTO n,deb,cred FROM ledger_entries WHERE ledger_transaction_id=jid;
      IF n <> 2 OR deb <> cred THEN
        RAISE EXCEPTION 'Journal must contain one balanced pair' USING ERRCODE='23514';
      END IF;
      IF j.kind='p2p_transfer' THEN
        SELECT status,amount_minor,completed_at,sender_wallet_id AS debit_wallet,
          receiver_wallet_id AS credit_wallet INTO o FROM transfers WHERE id=j.transfer_id;
      ELSE
        SELECT status,amount_minor,completed_at,NULL::uuid AS debit_wallet,
          wallet_id AS credit_wallet INTO o FROM sandbox_top_ups WHERE id=j.sandbox_top_up_id;
      END IF;
      IF NOT FOUND OR o.status <> 'completed' OR j.posted_at < o.completed_at THEN
        RAISE EXCEPTION 'Journal requires a completed source' USING ERRCODE='23514';
      END IF;
      SELECT count(*) INTO good FROM ledger_entries e JOIN ledger_accounts a ON a.id=e.ledger_account_id
      WHERE e.ledger_transaction_id=jid AND e.created_at=j.posted_at AND e.amount_minor=o.amount_minor
      AND ((e.side='credit' AND a.wallet_id=o.credit_wallet AND a.account_type='liability') OR
        (e.side='debit' AND ((j.kind='p2p_transfer' AND a.wallet_id=o.debit_wallet AND a.account_type='liability') OR
          (j.kind='sandbox_topup' AND a.wallet_id IS NULL AND a.account_type='asset' AND a.code='SYS:SIM_FUNDING:'||j.currency))));
      IF good <> 2 THEN RAISE EXCEPTION 'Journal entries do not match source' USING ERRCODE='23514'; END IF;
    END $$""",
    """CREATE OR REPLACE FUNCTION fincore_check_journal() RETURNS trigger
    LANGUAGE plpgsql SET search_path FROM CURRENT AS $$ BEGIN
      IF TG_TABLE_NAME='ledger_entries' THEN PERFORM fincore_validate_journal(NEW.ledger_transaction_id);
      ELSE PERFORM fincore_validate_journal(NEW.id); END IF;
      RETURN NULL;
    END $$""",
    """CREATE OR REPLACE FUNCTION fincore_check_source() RETURNS trigger
    LANGUAGE plpgsql SET search_path FROM CURRENT AS $$ DECLARE jid uuid;
    BEGIN
      IF TG_TABLE_NAME='transfers' THEN SELECT id INTO jid FROM ledger_transactions WHERE transfer_id=NEW.id;
      ELSE SELECT id INTO jid FROM ledger_transactions WHERE sandbox_top_up_id=NEW.id; END IF;
      IF (NEW.status='completed') <> (jid IS NOT NULL) THEN
        RAISE EXCEPTION 'Source status and journal must agree' USING ERRCODE='23514';
      END IF;
      IF jid IS NOT NULL THEN PERFORM fincore_validate_journal(jid); END IF;
      RETURN NULL;
    END $$""",
    """CREATE OR REPLACE FUNCTION fincore_check_replay() RETURNS trigger
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
    END $$""",
    """CREATE OR REPLACE FUNCTION fincore_lock_operator() RETURNS trigger
    LANGUAGE plpgsql SET search_path FROM CURRENT AS $$ BEGIN
      IF TG_OP='DELETE' THEN PERFORM 1 FROM users WHERE id=OLD.user_id FOR UPDATE; RETURN OLD;
      ELSE PERFORM 1 FROM users WHERE id=NEW.user_id FOR UPDATE; RETURN NEW; END IF;
    END $$""",
    "CREATE TRIGGER lock_operator BEFORE INSERT OR UPDATE OR DELETE ON sandbox_operators FOR EACH ROW EXECUTE FUNCTION fincore_lock_operator()",
    "CREATE CONSTRAINT TRIGGER check_replay AFTER INSERT OR UPDATE ON idempotency_records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fincore_check_replay()",
]
for table in ('transfers', 'sandbox_top_ups', 'ledger_transactions', 'ledger_entries'):
    LEDGER_GUARDS.append(f'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION fincore_immutable()')
    LEDGER_GUARDS.append(f'CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION fincore_immutable()')
LEDGER_GUARDS.extend([
    """CREATE OR REPLACE FUNCTION fincore_idempotency_digest(actor uuid, operation text, client_key text)
    RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
      SELECT encode(sha256(convert_to('[' || to_json(actor::text)::text || ',' ||
        to_json(operation)::text || ',' || to_json(client_key)::text || ']', 'UTF8')), 'hex')
    $$""",
    'CREATE TRIGGER immutable_receipt BEFORE UPDATE OR DELETE ON idempotency_receipts FOR EACH ROW EXECUTE FUNCTION fincore_immutable()',
    'CREATE TRIGGER immutable_receipt_truncate BEFORE TRUNCATE ON idempotency_receipts FOR EACH STATEMENT EXECUTE FUNCTION fincore_immutable()',
])
for table in ('transfers', 'sandbox_top_ups'):
    LEDGER_GUARDS.append(f'CREATE CONSTRAINT TRIGGER check_source AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fincore_check_source()')
for table in ('ledger_transactions', 'ledger_entries'):
    LEDGER_GUARDS.append(f'CREATE CONSTRAINT TRIGGER check_journal AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fincore_check_journal()')

LEDGER_GUARDS.extend([
    """CREATE OR REPLACE FUNCTION fincore_wallet_identity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF ROW(NEW.id,NEW.user_id,NEW.number,NEW.currency,NEW.created_at) IS DISTINCT FROM
         ROW(OLD.id,OLD.user_id,OLD.number,OLD.currency,OLD.created_at) THEN
        RAISE EXCEPTION 'Wallet identity is immutable' USING ERRCODE='23514';
      END IF; RETURN NEW;
    END $$""",
    """CREATE OR REPLACE FUNCTION fincore_account_identity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF ROW(NEW.id,NEW.wallet_id,NEW.code,NEW.account_type,NEW.currency,NEW.created_at) IS DISTINCT FROM
         ROW(OLD.id,OLD.wallet_id,OLD.code,OLD.account_type,OLD.currency,OLD.created_at) THEN
        RAISE EXCEPTION 'Account identity is immutable' USING ERRCODE='23514';
      END IF; RETURN NEW;
    END $$""",
    """CREATE OR REPLACE FUNCTION fincore_replay_identity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
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
    END $$""",
    "CREATE TRIGGER wallet_identity BEFORE UPDATE ON wallets FOR EACH ROW EXECUTE FUNCTION fincore_wallet_identity()",
    "CREATE TRIGGER account_identity BEFORE UPDATE ON ledger_accounts FOR EACH ROW EXECUTE FUNCTION fincore_account_identity()",
    "CREATE TRIGGER replay_identity BEFORE UPDATE OR DELETE ON idempotency_records FOR EACH ROW EXECUTE FUNCTION fincore_replay_identity()",
])


def register_ledger_guards(metadata):
    def after_create(target, connection, tables, **kwargs):
        if connection.dialect.name == 'postgresql' and any(table.name == 'ledger_transactions' for table in tables):
            for statement in LEDGER_GUARDS:
                connection.exec_driver_sql(statement)
    event.listen(metadata, 'after_create', after_create)

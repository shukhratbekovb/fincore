from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.reconciliation.dtos import (
    ReconciliationExample, ReconciliationFinding, ReconciliationReport,
)


# One SELECT observes one MVCC snapshot, including its summary and all checks.
# SUM(bigint) is numeric in PostgreSQL; Python int keeps aggregate precision.
RECONCILIATION_SQL = text("""
WITH wallet_postings AS (
    SELECT a.wallet_id,
        sum(CASE e.side WHEN 'credit' THEN e.amount_minor::numeric
            WHEN 'debit' THEN -e.amount_minor::numeric ELSE 0 END) AS posted_minor
    FROM ledger_accounts a JOIN ledger_entries e ON e.ledger_account_id = a.id
    WHERE a.wallet_id IS NOT NULL GROUP BY a.wallet_id
), journal_totals AS (
    SELECT j.id, count(e.id) AS entry_count,
        coalesce(sum(e.amount_minor) FILTER (WHERE e.side = 'debit'), 0) AS debit_minor,
        coalesce(sum(e.amount_minor) FILTER (WHERE e.side = 'credit'), 0) AS credit_minor
    FROM ledger_transactions j LEFT JOIN ledger_entries e ON e.ledger_transaction_id = j.id
    GROUP BY j.id
), sources AS (
    SELECT j.*, t.status AS transfer_status, s.status AS top_up_status,
        CASE WHEN j.kind = 'p2p_transfer' THEN t.amount_minor ELSE s.amount_minor END AS source_amount,
        CASE WHEN j.kind = 'p2p_transfer' THEN t.completed_at ELSE s.completed_at END AS source_completed_at,
        CASE WHEN j.kind = 'p2p_transfer' THEN t.currency ELSE s.currency END AS source_currency,
        t.sender_wallet_id AS debit_wallet,
        CASE WHEN j.kind = 'p2p_transfer' THEN t.receiver_wallet_id ELSE s.wallet_id END AS credit_wallet
    FROM ledger_transactions j LEFT JOIN transfers t ON t.id = j.transfer_id
        LEFT JOIN sandbox_top_ups s ON s.id = j.sandbox_top_up_id
), operations AS (
    SELECT 'transfer'::text AS entity_type, t.id, t.currency, t.status, count(j.id) AS journal_count
    FROM transfers t LEFT JOIN ledger_transactions j ON j.transfer_id = t.id GROUP BY t.id
    UNION ALL
    SELECT 'sandbox_top_up', s.id, s.currency, s.status, count(j.id)
    FROM sandbox_top_ups s LEFT JOIN ledger_transactions j ON j.sandbox_top_up_id = s.id GROUP BY s.id
), issues AS (
    SELECT 'wallet_balance_missing'::text AS code, 'wallet'::text AS entity_type, w.id AS entity_id,
        w.currency, NULL::numeric AS expected_minor, NULL::numeric AS actual_minor
    FROM wallets w LEFT JOIN wallet_balances b ON b.wallet_id = w.id WHERE b.wallet_id IS NULL
    UNION ALL
    SELECT 'wallet_account_missing', 'wallet', w.id, w.currency, NULL, NULL
    FROM wallets w LEFT JOIN ledger_accounts a ON a.wallet_id = w.id WHERE a.id IS NULL
    UNION ALL
    SELECT 'wallet_account_invalid', 'wallet', w.id, w.currency, NULL, NULL
    FROM wallets w JOIN ledger_accounts a ON a.wallet_id = w.id
    GROUP BY w.id HAVING count(*) <> 1 OR bool_or(
        a.currency IS DISTINCT FROM w.currency OR a.account_type IS DISTINCT FROM 'liability'
        OR a.code IS DISTINCT FROM 'WALLET:' || w.id::text || ':' || w.currency
        OR a.status IS DISTINCT FROM CASE WHEN w.status = 'closed' THEN 'closed' ELSE 'active' END)
    UNION ALL
    SELECT 'wallet_balance_invalid', 'wallet', w.id, w.currency, NULL, b.posted_minor
    FROM wallets w JOIN wallet_balances b ON b.wallet_id = w.id
    WHERE b.posted_minor < 0 OR b.version < 0
    UNION ALL
    SELECT 'wallet_balance_mismatch', 'wallet', w.id, w.currency, coalesce(p.posted_minor, 0), b.posted_minor
    FROM wallets w JOIN wallet_balances b ON b.wallet_id = w.id
        LEFT JOIN wallet_postings p ON p.wallet_id = w.id
    WHERE b.posted_minor IS DISTINCT FROM coalesce(p.posted_minor, 0)
    UNION ALL
    SELECT 'wallet_balance_orphan', 'wallet', b.wallet_id, NULL, NULL, b.posted_minor
    FROM wallet_balances b LEFT JOIN wallets w ON w.id = b.wallet_id WHERE w.id IS NULL
    UNION ALL
    SELECT 'ledger_account_invalid', 'ledger_account', a.id, a.currency, NULL, NULL
    FROM ledger_accounts a LEFT JOIN wallets w ON w.id = a.wallet_id
    WHERE (a.wallet_id IS NOT NULL AND w.id IS NULL)
        OR (a.wallet_id IS NULL AND (a.account_type IS DISTINCT FROM 'asset'
            OR a.code IS DISTINCT FROM 'SYS:SIM_FUNDING:' || a.currency OR a.status NOT IN ('active', 'closed')))
        OR a.currency NOT IN ('USD','EUR','JPY','CHF','GBP','UZS','CAD','RUB')
    UNION ALL
    SELECT 'journal_unbalanced', 'ledger_transaction', j.id, j.currency, t.debit_minor, t.credit_minor
    FROM ledger_transactions j JOIN journal_totals t ON t.id = j.id
    WHERE t.entry_count <> 2 OR t.debit_minor <> t.credit_minor
    UNION ALL
    SELECT 'entry_invalid', 'ledger_entry', e.id, e.currency, NULL, e.amount_minor
    FROM ledger_entries e LEFT JOIN ledger_transactions j ON j.id = e.ledger_transaction_id
        LEFT JOIN ledger_accounts a ON a.id = e.ledger_account_id
    WHERE j.id IS NULL OR a.id IS NULL OR e.amount_minor <= 0 OR e.side NOT IN ('debit','credit')
        OR e.currency IS DISTINCT FROM j.currency OR e.currency IS DISTINCT FROM a.currency
        OR e.created_at IS DISTINCT FROM j.posted_at
    UNION ALL
    SELECT 'journal_source_invalid', 'ledger_transaction', s.id, s.currency, NULL, NULL
    FROM sources s WHERE NOT (
        ((s.kind = 'p2p_transfer' AND s.transfer_id IS NOT NULL AND s.sandbox_top_up_id IS NULL
            AND s.transfer_status = 'completed')
        OR (s.kind = 'sandbox_topup' AND s.sandbox_top_up_id IS NOT NULL AND s.transfer_id IS NULL
            AND s.top_up_status = 'completed'))
        AND s.source_currency = s.currency AND s.source_completed_at IS NOT NULL
        AND s.posted_at >= s.source_completed_at) IS TRUE
    UNION ALL
    SELECT 'journal_entries_mismatch', 'ledger_transaction', s.id, s.currency, s.source_amount, NULL
    FROM sources s LEFT JOIN ledger_entries e ON e.ledger_transaction_id = s.id
        LEFT JOIN ledger_accounts a ON a.id = e.ledger_account_id
    GROUP BY s.id, s.currency, s.source_amount, s.posted_at, s.credit_wallet, s.debit_wallet, s.kind
    HAVING count(e.id) FILTER (WHERE e.amount_minor = s.source_amount
        AND e.currency = s.currency AND a.currency = s.currency AND e.created_at = s.posted_at
        AND ((e.side = 'credit' AND a.wallet_id = s.credit_wallet AND a.account_type = 'liability')
        OR (e.side = 'debit' AND ((s.kind = 'p2p_transfer' AND a.wallet_id = s.debit_wallet AND a.account_type = 'liability')
        OR (s.kind = 'sandbox_topup' AND a.wallet_id IS NULL AND a.account_type = 'asset'
            AND a.code = 'SYS:SIM_FUNDING:' || s.currency))))) <> 2
    UNION ALL
    SELECT 'operation_journal_count_invalid', o.entity_type, o.id, o.currency, NULL, NULL
    FROM operations o WHERE (o.status = 'completed' AND o.journal_count <> 1)
        OR (o.status = 'rejected' AND o.journal_count <> 0) OR o.status NOT IN ('completed', 'rejected')
), ranked AS (
    SELECT *, count(*) OVER (PARTITION BY code) AS issue_count,
        row_number() OVER (PARTITION BY code ORDER BY entity_type, entity_id) AS sample_number
    FROM issues
), totals AS (
    SELECT statement_timestamp() AS as_of,
        (SELECT count(*) FROM wallets) AS wallets_checked,
        (SELECT count(*) FROM ledger_transactions) AS journals_checked,
        (SELECT count(*) FROM ledger_entries) AS entries_checked
)
SELECT totals.*, ranked.code, ranked.issue_count, ranked.entity_type, ranked.entity_id,
    ranked.currency, ranked.expected_minor, ranked.actual_minor
FROM totals LEFT JOIN ranked ON ranked.sample_number <= :sample_limit
ORDER BY ranked.code, ranked.sample_number
""")


class SqlAlchemyLedgerReconciliationReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def reconcile(self, *, sample_limit: int) -> ReconciliationReport:
        if type(sample_limit) is not int or not 1 <= sample_limit <= 100:
            raise ValueError("Sample limit must be an integer between 1 and 100")
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION READ ONLY"))
                rows = (await session.execute(RECONCILIATION_SQL, {"sample_limit": sample_limit})).mappings().all()
        groups = {}
        for row in rows:
            if row['code'] is None:
                continue
            count, examples = groups.setdefault(row['code'], (int(row['issue_count']), []))
            examples.append(ReconciliationExample(
                entity_type=row['entity_type'], entity_id=row['entity_id'], currency=row['currency'],
                expected_minor=int(row['expected_minor']) if row['expected_minor'] is not None else None,
                actual_minor=int(row['actual_minor']) if row['actual_minor'] is not None else None,
            ))
        first = rows[0]
        return ReconciliationReport(
            as_of=first['as_of'], wallets_checked=int(first['wallets_checked']),
            journals_checked=int(first['journals_checked']), entries_checked=int(first['entries_checked']),
            findings=tuple(ReconciliationFinding(code, count, tuple(examples))
                           for code, (count, examples) in groups.items()),
        )

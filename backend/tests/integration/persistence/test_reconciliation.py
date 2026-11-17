from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.application.reconciliation.dtos import ReconcileLedgerCommand
from backend.application.reconciliation.queries.reconcile_ledger import ReconcileLedgerQuery
from backend.domain.ledger_account.entities import LedgerAccount
from backend.domain.ledger_transaction.entities import LedgerTransaction
from backend.domain.sandbox_top_up.entities import SandboxTopUp
from backend.domain.share.enums import CurrencyEnum
from backend.domain.user.entities import User
from backend.domain.user.value_objects import Username, Email, HashedPassword
from backend.domain.wallet.entities import Wallet
from backend.domain.wallet.value_objects import WalletName, WalletNumber
from backend.domain.wallet_balance.entities import WalletBalance
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork
from backend.infrastructure.db.sqlalchemy.readers.reconciliation import SqlAlchemyLedgerReconciliationReader


async def report(factory, limit=10):
    return await ReconcileLedgerQuery(SqlAlchemyLedgerReconciliationReader(factory)).execute(ReconcileLedgerCommand(limit))


@pytest.fixture
async def seeded(session_factory, now):
    user = User.created_by_admin(Username('reconcile'), Email('reconcile@example.com'), HashedPassword('test-hash'))
    wallets, accounts = [], []
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.users.add(user)
        for index, currency in enumerate((CurrencyEnum.USD, CurrencyEnum.EUR, CurrencyEnum.USD)):
            wallet = Wallet.create(user_id=user.id, name=WalletName('Main'),
                                   number=WalletNumber(str(index + 1).zfill(20)), currency=currency)
            account = LedgerAccount.for_wallet(wallet_id=wallet.id, currency=currency, now=now)
            await uow.wallets.add(wallet)
            await uow.wallet_balances.add(WalletBalance.create(wallet_id=wallet.id, now=now))
            await uow.ledger_accounts.add(account)
            wallets.append(wallet)
            accounts.append(account)
        funding = LedgerAccount.for_sandbox_funding(currency=CurrencyEnum.USD, now=now)
        await uow.ledger_accounts.add(funding)
        top_up = SandboxTopUp.create(wallet_id=wallets[0].id, initiated_by_user_id=user.id,
                                     amount_minor=2 ** 63 - 1, currency=CurrencyEnum.USD, now=now)
        top_up.complete(now)
        journal = LedgerTransaction.for_sandbox_top_up(top_up=top_up, funding_account=funding,
                                                      wallet_account=accounts[0], now=now)
        await uow.sandbox_top_ups.add(top_up)
        await uow.ledger_transactions.add(journal)
        balance = await uow.wallet_balances.get_by_wallet_id_for_update(wallets[0].id)
        balance.credit(top_up.amount_minor, now=now)
        await uow.wallet_balances.save(balance)
        await uow.commit()
    return SimpleNamespace(factory=session_factory, user=user, wallets=wallets,
                           accounts=accounts, funding=funding, top_up=top_up, journal=journal)


async def corrupt(ctx, statements):
    # Deliberately bypass defense-in-depth ONLY in the random, disposable test
    # schema. Reconciliation must detect legacy/import or privileged corruption.
    async with ctx.factory.begin() as session:
        for statement, parameters in statements:
            await session.execute(text(statement), parameters)


def findings(result):
    return {finding.code: finding for finding in result.findings}


async def test_empty_database_is_consistent(session_factory):
    result = await report(session_factory)
    assert result.is_consistent and result.issue_count == 0
    assert (result.wallets_checked, result.journals_checked, result.entries_checked) == (0, 0, 0)
    assert result.as_of.tzinfo is not None


async def test_real_postings_max_bigint_and_frozen_closed_wallets_are_consistent(seeded):
    await corrupt(seeded, [
        ("UPDATE wallets SET status='frozen' WHERE id=:id", {'id': seeded.wallets[0].id}),
        ("UPDATE wallets SET status='closed' WHERE id=:id", {'id': seeded.wallets[1].id}),
        ("UPDATE ledger_accounts SET status='closed' WHERE id=:id", {'id': seeded.accounts[1].id}),
    ])
    result = await report(seeded.factory)
    assert result.is_consistent, result.findings
    assert (result.wallets_checked, result.journals_checked, result.entries_checked) == (3, 1, 2)


async def test_drift_reports_full_counts_but_bounded_deterministic_samples_and_never_repairs(seeded):
    await corrupt(seeded, [("UPDATE wallet_balances SET posted_minor=1", {})])
    result = await report(seeded.factory, 2)
    mismatch = findings(result)['wallet_balance_mismatch']
    assert mismatch.count == 3 and len(mismatch.examples) == 2
    assert [example.entity_id for example in mismatch.examples] == sorted(wallet.id for wallet in seeded.wallets)[:2]
    assert result.issue_count == 3
    async with seeded.factory() as session:
        assert (await session.execute(text('SELECT DISTINCT posted_minor FROM wallet_balances'))).scalars().all() == [1]
    assert (await report(seeded.factory, 2)).findings == result.findings


async def test_missing_projection_and_account_are_distinct_from_zero_balance(seeded):
    await corrupt(seeded, [
        ("DELETE FROM wallet_balances WHERE wallet_id=:id", {'id': seeded.wallets[1].id}),
        ("DELETE FROM ledger_accounts WHERE id=:id", {'id': seeded.accounts[2].id}),
    ])
    errors = findings(await report(seeded.factory))
    assert set(errors) == {'wallet_balance_missing', 'wallet_account_missing'}
    assert errors['wallet_balance_missing'].examples[0].entity_id == seeded.wallets[1].id


async def test_unbalanced_and_currency_corruption_detected_even_when_constraints_bypassed(seeded):
    credit = next(entry for entry in seeded.journal.entries if entry.side.value == 'credit')
    await corrupt(seeded, [
        ('ALTER TABLE ledger_entries DISABLE TRIGGER ALL', {}),
        ('UPDATE ledger_entries SET amount_minor=amount_minor-1, currency=\'EUR\' WHERE id=:id', {'id': credit.id}),
    ])
    errors = findings(await report(seeded.factory))
    assert {'journal_unbalanced', 'entry_invalid', 'journal_entries_mismatch', 'wallet_balance_mismatch'} <= errors.keys()
    mismatch = errors['wallet_balance_mismatch'].examples[0]
    assert mismatch.expected_minor == 2 ** 63 - 2 and mismatch.actual_minor == 2 ** 63 - 1
    assert type(mismatch.expected_minor) is type(mismatch.actual_minor) is int


async def test_balanced_wrong_source_amount_is_detected(seeded):
    await corrupt(seeded, [
        ('ALTER TABLE ledger_entries DISABLE TRIGGER USER', {}),
        ('UPDATE ledger_entries SET amount_minor=100', {}),
        ('UPDATE wallet_balances SET posted_minor=100 WHERE wallet_id=:id', {'id': seeded.wallets[0].id}),
    ])
    errors = findings(await report(seeded.factory))
    assert set(errors) == {'journal_entries_mismatch'}


async def test_completed_without_journal_and_rejected_with_journal(seeded):
    await corrupt(seeded, [
        ('ALTER TABLE sandbox_top_ups DISABLE TRIGGER USER', {}),
        ("UPDATE sandbox_top_ups SET status='rejected', completed_at=NULL, rejection_code='limit_exceeded'", {}),
    ])
    errors = findings(await report(seeded.factory))
    assert {'journal_source_invalid', 'operation_journal_count_invalid'} <= errors.keys()
    await corrupt(seeded, [
        ('ALTER TABLE ledger_entries DISABLE TRIGGER ALL', {}),
        ('ALTER TABLE ledger_transactions DISABLE TRIGGER ALL', {}),
        ('DELETE FROM ledger_entries', {}),
        ('DELETE FROM ledger_transactions', {}),
        ("UPDATE sandbox_top_ups SET status='completed', completed_at=updated_at, rejection_code=NULL", {}),
    ])
    assert 'operation_journal_count_invalid' in findings(await report(seeded.factory))


async def test_duplicate_source_journals_are_detected(seeded):
    await corrupt(seeded, [
        ('ALTER TABLE ledger_transactions DISABLE TRIGGER USER', {}),
        ('ALTER TABLE ledger_transactions DROP CONSTRAINT uq_journals_top_up', {}),
        ("INSERT INTO ledger_transactions (id,kind,currency,posted_at,sandbox_top_up_id) "
         "SELECT :id,kind,currency,posted_at,sandbox_top_up_id FROM ledger_transactions", {'id': uuid4()}),
    ])
    errors = findings(await report(seeded.factory))
    assert errors['operation_journal_count_invalid'].count == 1
    assert errors['journal_unbalanced'].count == 1


async def test_inflight_projection_change_is_invisible_until_commit(seeded):
    async with seeded.factory.begin() as writer:
        await writer.execute(text('UPDATE wallet_balances SET posted_minor=0 WHERE wallet_id=:id'),
                             {'id': seeded.wallets[0].id})
        result = await report(seeded.factory)
        assert result.is_consistent
    assert 'wallet_balance_mismatch' in findings(await report(seeded.factory))


async def test_invalid_account_and_orphan_entries_have_explicit_findings(seeded):
    await corrupt(seeded, [
        ('ALTER TABLE ledger_accounts DISABLE TRIGGER ALL', {}),
        ('ALTER TABLE ledger_accounts DROP CONSTRAINT ck_ledger_accounts_purpose', {}),
        ("UPDATE ledger_accounts SET account_type='asset' WHERE id=:id", {'id': seeded.accounts[0].id}),
        ('ALTER TABLE ledger_entries DISABLE TRIGGER ALL', {}),
        ('UPDATE ledger_entries SET ledger_account_id=:id WHERE side=\'debit\'', {'id': uuid4()}),
    ])
    errors = findings(await report(seeded.factory))
    assert {'wallet_account_invalid', 'entry_invalid', 'journal_entries_mismatch'} <= errors.keys()


@pytest.mark.parametrize('limit', [0, True, 101])
async def test_adapter_rejects_unbounded_samples_without_connecting(limit):
    def no_connection():
        raise AssertionError('Invalid request reached database')
    with pytest.raises(ValueError):
        await SqlAlchemyLedgerReconciliationReader(no_connection).reconcile(sample_limit=limit)


async def test_commit_during_scan_cannot_mix_old_and_new_snapshots(seeded, monkeypatch):
    import asyncio
    from backend.infrastructure.db.sqlalchemy.readers import reconciliation as reader_module
    lock_key = uuid4().int % (2 ** 62)
    # Instrument only a pause; execute the actual production query unchanged
    # otherwise. Its snapshot must predate the writer commit releasing the lock.
    delayed_sql = reader_module.RECONCILIATION_SQL.text.replace(
        'WITH wallet_postings AS (',
        f'WITH barrier AS MATERIALIZED (SELECT pg_advisory_xact_lock({lock_key})), wallet_postings AS (',
    ).replace('FROM totals LEFT JOIN ranked', 'FROM totals CROSS JOIN barrier LEFT JOIN ranked')
    monkeypatch.setattr(reader_module, 'RECONCILIATION_SQL', text(delayed_sql))
    scan = None
    try:
        async with seeded.factory.begin() as writer:
            await writer.execute(text(f'SELECT pg_advisory_xact_lock({lock_key})'))
            await writer.execute(text('UPDATE wallet_balances SET posted_minor=0 WHERE wallet_id=:id'),
                                 {'id': seeded.wallets[0].id})
            scan = asyncio.create_task(report(seeded.factory))
            async with seeded.factory() as observer:
                # pg_locks reflects current lock-manager state on every query;
                # pg_stat_activity would cache a statistics snapshot in this transaction.
                for _ in range(100):
                    waiting = await observer.scalar(text(
                        "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted "
                        "AND classid::bigint=:lock_class AND objid::bigint=:lock_object AND objsubid=1 "
                        "AND database=(SELECT oid FROM pg_database WHERE datname=current_database())"
                    ), {'lock_class': lock_key >> 32, 'lock_object': lock_key & 0xFFFFFFFF})
                    if waiting:
                        break
                    await asyncio.sleep(0.01)
                else:
                    pytest.fail('Reconciliation never reached snapshot barrier')
        result = await asyncio.wait_for(scan, timeout=3)
        assert result.is_consistent
        monkeypatch.undo()
        assert 'wallet_balance_mismatch' in findings(await report(seeded.factory))
    finally:
        if scan is not None and not scan.done():
            scan.cancel()
            await asyncio.gather(scan, return_exceptions=True)


async def test_orphan_projection_and_invalid_funding_account_are_reported(seeded, now):
    orphan_id = uuid4()
    await corrupt(seeded, [
        ('ALTER TABLE wallet_balances DISABLE TRIGGER ALL', {}),
        ('INSERT INTO wallet_balances (wallet_id,posted_minor,version,created_at,updated_at) '
         'VALUES (:id,10,0,:now,:now)', {'id': orphan_id, 'now': now}),
        ('ALTER TABLE ledger_accounts DISABLE TRIGGER ALL', {}),
        ('ALTER TABLE ledger_accounts DROP CONSTRAINT ck_ledger_accounts_purpose', {}),
        ("UPDATE ledger_accounts SET code='WRONG:FUNDING:USD' WHERE id=:id", {'id': seeded.funding.id}),
    ])
    errors = findings(await report(seeded.factory))
    assert errors['wallet_balance_orphan'].examples[0].entity_id == orphan_id
    assert errors['ledger_account_invalid'].examples[0].entity_id == seeded.funding.id
    assert 'journal_entries_mismatch' in errors

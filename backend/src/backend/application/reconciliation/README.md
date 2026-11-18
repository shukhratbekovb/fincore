# Сверка ledger / Ledger reconciliation

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

`ReconcileLedgerQuery` — служебный запрос только для чтения. У него нет публичного
HTTP-эндпоинта; он не исправляет балансы и не переписывает неизменяемые журналы.

Application зависит от `ILedgerReconciliationReader`. PostgreSQL-адаптер владеет
отдельной READ ONLY транзакцией и выполняет **один SELECT**, поэтому итоги,
нарушения и примеры читаются из одного MVCC snapshot даже при конкурентном
commit переводов. Он намеренно отделён от записывающего UoW и не блокирует строки.

Проверки охватывают:

- Кошельки без баланса или ledger account; соответствие идентификаторов, валюты, типа и статуса счёта.
- Отсутствующие ссылки на кошельки и некорректные системные funding accounts.
- Отрицательные значения/версии проекции и расхождение баланса с суммой credit
  минус debit по всем счетам кошельков, включая закрытые/замороженные.
- Итоги debit/credit журнала и текущий контракт двух проводок.
- Сумму/сторону проводки, ссылки на счёт и журнал, валюту и время проведения.
- Вид журнала, ровно один завершённый бизнес-источник, его валюту и время.
- Точное совпадение суммы и пары debit/credit счетов кошельков либо системного funding account с источником.
- Ровно один журнал завершённого перевода/пополнения и отсутствие журнала у отклонённых.

Суммы — Python int; PostgreSQL агрегирует BIGINT в NUMERIC. Валюты не конвертируются
и не складываются между собой. Версия проверяется на неотрицательность, а не на
равенство количеству проводок: это версия для оптимистической конкуренции.

Отчёт содержит полные количества и не более `sample_limit` примеров **на каждый
код нарушения** (по умолчанию 10, допустимо 1..100) с детерминированным порядком
по идентификатору сущности. `issue_count` считает неуспешные проверки, а не
уникальные повреждённые сущности: одна сущность может попасть в несколько групп.
Ограничение примеров не ограничивает сканирование. Пустой корректный ledger
считается согласованным. Отсутствующие/недоступные таблицы и SQL-ошибки являются
ошибками выполнения, а не успешным пустым отчётом.

Запуск из `backend` с настроенным DATABASE_URL:

```sh
poetry run python -m backend.bootstrap.reconcile_ledger --sample-limit 10
```

Коды завершения: `0` — согласованность; `1` — обнаружены нарушения;
`2` — ошибка выполнения или аргументов. JSON-отчёт выводится в stdout;
ошибки выполнения дают безопасное сообщение в stderr без параметров соединения.
В Docker тот же модуль можно запускать внутри API-образа. Отчёт не должен быть
публичным: примеры содержат ID и внутренние учётные суммы.

Запускайте вручную или по расписанию. Сканируется финансовая история, поэтому
стоимость растёт с ledger: выбирайте время вне пика, следите за длительностью
и используйте роль соединения только с SELECT. Корректность опирается на snapshot
одного statement, а не на привилегии или отключение ограничений. Ограничения БД
остаются первой защитой; сверка независимо обнаруживает дрейф проекции и
повреждения старых/импортированных данных. Чистый отчёт не доказывает отсутствие
согласованной подмены всех исходных и учётных записей.

<a id="en"></a>

## English

`ReconcileLedgerQuery` is an operational, read-only query. It has no public HTTP
endpoint and does not repair balances or rewrite immutable journals.

The application depends on `ILedgerReconciliationReader`. The PostgreSQL adapter
owns a separate READ ONLY transaction and performs **one SELECT**, so totals,
findings and examples observe the same MVCC snapshot even while transfers commit.
It is intentionally separate from the write UoW. It takes no row locks.

Checks cover:

- Wallets missing a balance or ledger account; account identity/currency/type/status.
- Missing wallet references and invalid system funding accounts.
- Negative projection values/versions and balance mismatch against credit minus
  debit postings on all wallet accounts, including closed/frozen wallets.
- Journal debit/credit totals and the current two-entry posting contract.
- Entry amount/side, account and journal references, currency, posting timestamp.
- Journal kind, exactly one completed business source, source currency/time.
- Exact source amount and debit/credit wallet or system funding account pairing.
- Exactly one journal for completed transfers/top-ups, none for rejected ones.

Amounts are Python integers; PostgreSQL aggregates BIGINT into NUMERIC. Currencies
are never converted or added together. Version is checked for non-negativity,
not equality with entry count: it is an optimistic concurrency version.

The report includes complete counts and at most `sample_limit` examples **per
finding code** (default 10, allowed 1..100), ordered deterministically by entity
identity. `issue_count` counts failed checks, not unique corrupted entities: one
entity can appear under several findings. Sampling does not limit the scan.
A clean empty ledger is consistent. Missing/inaccessible tables and SQL failures
are execution failures, never a successful empty report.

Run from `backend` with configured DATABASE_URL:

```sh
poetry run python -m backend.bootstrap.reconcile_ledger --sample-limit 10
```

Exit codes: `0` consistent; `1` findings; `2` execution or argument failure.
Stdout contains the JSON report; execution failures produce a sanitized stderr
message without connection parameters. Docker operators can run the same module
inside the API image. Do not expose its output publicly: examples contain IDs
and internal accounting amounts.

Run on demand or via a scheduled job. This scans financial history, so its cost
grows with ledger size; schedule it away from peak load, monitor duration and
use a connection role with SELECT permissions only. Correctness relies on one
statement snapshot, not on privileged access or disabled constraints. Integrity
constraints remain the first line of defense; reconciliation independently
catches projection drift and legacy/import corruption. A clean report is not a
proof against coordinated tampering with every source and accounting record.

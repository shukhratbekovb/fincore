# Тесты PostgreSQL / PostgreSQL integration tests

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

Тесты используют только явно заданный `FINCORE_TEST_DATABASE_URL`, не рабочий
`DATABASE_URL`. Требуется `postgresql+asyncpg` и имя БД с суффиксом `_test`.
При отсутствии переменной этот набор пропускается; unit-тесты продолжают работать.
Каждый тест создаёт отдельную случайную схему и удаляет её в teardown.

```bash
FINCORE_TEST_DATABASE_URL='postgresql+asyncpg://user:password@localhost:5432/fincore_test' \
  poetry run pytest tests/integration/persistence -v
```

Проверяются сохранение/чтение доменных объектов, commit/rollback, FK и UNIQUE,
регистрация с outbox, подтверждение, login, ротация и повторное использование
refresh-токена, конкурентный refresh, смена пароля, logout, создание/переименование/
закрытие кошелька, актуальность заблокированного чтения и цикл миграций Alembic.
Финансовые проверки дополнительно проходят весь путь HTTP → use case/query →
PostgreSQL: transfer, sandbox top-up, history и balance; проверяются ACL,
подписанные cursors, конкурентные ключи/списания, rollback и неизменяемый journal.
Sandbox здесь оперирует виртуальными средствами, внешние платёжные сервисы
не подключаются. Почтовые тесты используют отдельно настроенный локальный Mailpit.
Сквозные registration/password-reset тесты и финансовые endpoints также требуют
FINCORE_TEST_REDIS_URL отдельного Redis.
Атомарность, TTL и общий бюджет между Redis pools проверяются в
tests/integration/test_redis_rate_limiter.py; PostgreSQL счётчики запросов удалены.

<a id="en"></a>

## English

Tests use only the explicitly supplied `FINCORE_TEST_DATABASE_URL`, never the
working `DATABASE_URL`. The driver must be `postgresql+asyncpg` and the database
name must end in `_test`. Without this variable, this suite is skipped while unit
tests still run. Each test creates a random isolated schema and drops it in teardown.

```bash
FINCORE_TEST_DATABASE_URL='postgresql+asyncpg://user:password@localhost:5432/fincore_test' \
  poetry run pytest tests/integration/persistence -v
```

Checks cover domain object persistence/reads, commit/rollback, FK and UNIQUE,
registration with outbox, confirmation, login, refresh token rotation and reuse,
concurrent refresh, password changes, logout, wallet creation/renaming/closure,
fresh locked reads and the Alembic migration cycle.
Financial checks also exercise HTTP → use case/query → PostgreSQL for transfers,
sandbox top-ups, history and balances, including ACL, signed cursors, competing
keys/debits, rollback and immutable journals. Sandbox uses virtual funds and does
not connect to external payment services. Email tests use a separately configured
local Mailpit. End-to-end registration/password-reset tests and financial endpoints
also require FINCORE_TEST_REDIS_URL pointing to a separate Redis instance.
Atomicity, TTL and shared budgets across Redis pools are tested in
`tests/integration/test_redis_rate_limiter.py`; PostgreSQL request counters have
been removed.

# PostgreSQL integration tests

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

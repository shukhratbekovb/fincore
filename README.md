# FinCore

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

FinCore — учебная платформа цифровых кошельков для переводов виртуальных CAD. Это портфолио-проект с упором на backend: согласованность транзакций, двойная запись, управление конкурентным доступом и идемпотентность денежных операций. Реальные деньги, банки и платёжные провайдеры не используются.

### Статус проекта

Обновление реализации: 17 ноября 2026 года.

Исходная документация: 15 октября 2026 года, на основе **FinCore PRD MVP v1.0** от 14 октября 2026 года. Требования и проектные предложения ниже сами по себе не означают, что функциональность реализована.

Backend реализует авторизацию, сессии, кошельки, sandbox-пополнения, переводы,
запросы ledger/истории/балансов, лимиты запросов Redis, заморозку/разморозку
владельцем и сверку без изменения данных. Корневой Docker Compose запускает
frontend, API, почтовый worker, обслуживание, PostgreSQL, Redis и миграции;
см. [развёртывание на VPS](docs/deployment.md). Next.js frontend в `frontend/`
подключён к API через серверный gateway с HttpOnly session cookies;
см. [настройку локальной интеграции](frontend/README.md).
GitHub Actions проверяет покрытие backend, frontend и сборку контейнеров.
Реальное развёртывание на VPS и доставка через SES на production-домене ещё требуют проверки.

### MVP

[Согласованное изменение от 16 октября 2026 года](docs/scope-update-2026-10-16.md)
заменяет исходное ограничение одного кошелька и добавляет пять разделов навигации
и профиль. Подробности backend описаны в [его README](backend/README.md).

- Регистрация с подтверждением email, повторная отправка подтверждения, вход, ротация refresh-сессий и выход.
- Несколько именованных CAD-кошельков на пользователя, показанных карточками; переводы между разными кошельками, включая собственные.
- Sandbox-пополнения с правами оператора и синхронные P2P-переводы.
- Неизменяемый ledger с двойной записью и атомарной проекцией баланса.
- Идемпотентные запросы изменения средств и история с курсорной пагинацией.
- Проверка прав владельца/участника и аудиторский след.

Банковские карты, реальные платежи, обмен валют, комиссии, возвраты, холды,
регулярные переводы, KYC, аналитика/экспорт и публичная админ-панель не входят в MVP.

### Стек

Backend: Python 3.13+, FastAPI, Pydantic, SQLAlchemy, asyncpg, Alembic, Uvicorn и
redis-py; зависимости управляются Poetry. PostgreSQL хранит финансовые данные,
Redis ограничивает частоту запросов. Frontend: Next.js App Router, React,
TypeScript, Tailwind CSS, Lucide, next-themes и Zod.
См. [README frontend](frontend/README.md).

### Запуск подключённого frontend

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

После запуска backend и почтового worker откройте http://localhost:3000.
Зарегистрируйтесь, подтвердите email через локальный Mailpit и войдите.
Кошельки, переводы, история, сессии и пароли работают через реальный API.
Настройки подключения, права sandbox-оператора и сквозные проверки описаны
в [документации frontend](frontend/README.md).

### Локальный запуск backend

Требуются Python, совместимый с `backend/pyproject.toml`, и установленный Poetry.

```bash
cd backend
poetry install
cp .env.example .env
# Настройте доступы, затем запустите PostgreSQL/Redis и примените миграции.
make infra
poetry run alembic upgrade head
poetry run uvicorn backend.main:app --app-dir src --reload
```

Префикс API — `/v1`. `/health` и `/health/live` проверяют, что процесс работает;
`/health/ready` проверяет PostgreSQL и Redis. Документация RU/EN и полная локальная
настройка описаны в [README backend](backend/README.md). Для отправки писем
подтверждения/сброса отдельно запустите outbox worker.

### Docker на VPS

В корне репозитория скопируйте `.env.example` в `.env`, настройте секреты БД/JWT
и SES SMTP, затем выполните:

```bash
docker compose up -d --build --wait
```

Frontend доступен на `127.0.0.1:3000`; порты API, PostgreSQL и Redis не опубликованы.
Задайте публичный HTTPS origin и отдельный секрет прокси, затем настройте reverse
proxy на перезапись обязательных ingress-заголовков. Миграции завершаются до
запуска сервисов приложения. Проверки состояния, логи, обновления и необязательный
локальный Mailpit описаны в [инструкции развёртывания](docs/deployment.md).
Владелец проекта настраивает Nginx отдельно; резервное копирование и сервисы
мониторинга не разворачиваются.

### Документация

Начните с [оглавления документации](docs/README.md).

- [Архитектура](docs/architecture.md) и [модель данных / ERD](docs/data-model.md)
- [Контракт API и ошибки](docs/api.md)
- [Финансовые инварианты](docs/invariants.md) и [план приёмочных проверок](docs/test-plan.md)
- [Спецификация frontend](docs/frontend-spec.md)
- [Открытые решения](docs/decisions.md) и [план поставки](docs/delivery-plan.md)
- [ADR-001: Ledger](docs/adr/ADR-001-ledger.md)
- [ADR-002: Идемпотентность](docs/adr/ADR-002-idempotency.md)

### План демонстрации

Подготовить синтетических пользователей Alice и Bob и отдельного sandbox-оператора.
Оператор пополняет Alice на CAD 500.00; Alice переводит Bob CAD 100.00.
Ожидаемые балансы: Alice CAD 400.00, Bob CAD 100.00. Повтор того же запроса
с тем же ключом идемпотентности должен вернуть исходный результат без второго
списания. Отказы, тайм-ауты и конкуренция описаны в [плане проверок](docs/test-plan.md).

### Требования к выпуску

[CI workflow](.github/workflows/ci.yml) запускается при push, pull request и вручную.
Он требует покрытия строк/ветвлений backend не ниже 91% на Python 3.13/3.14
с настоящими PostgreSQL, Redis и Mailpit, запрещает пропуски тестов, проверяет
frontend, браузерные сценарии и полный production Docker-стек.
См. [описание CI](docs/ci.md) и [отчёт проверок 17 ноября](docs/test-report-2026-11-17.md).
Отчёты хранятся 14 дней. Защиту ветки настройте отдельно, сделав
**CI required checks** обязательным перед merge. Автоматического развёртывания
или публикации нет.

Очистка служебных данных выполняется при старте maintenance-контейнера, затем
ежедневно. Полные записи идемпотентности хранятся минимум семь дней; компактные
постоянные квитанции сохраняют возможность безопасного позднего повтора денежных
запросов. Политика, пробный запуск и ограничения отката описаны
в [обслуживании](docs/maintenance.md).

Финансовые приёмочные тесты должны проходить на реальном PostgreSQL, включая
rollback, сверку и конкурентное списание. Для публикации нужны воспроизводимая
настройка, синтетические начальные данные, результаты CI и отчёт тестирования.
Frontend должен проверять истёкшие сессии, границы доступа, точный ввод денежных
сумм и безопасные повторы. См. [критерии поставки](docs/delivery-plan.md).

<a id="en"></a>

## English

FinCore is an educational digital wallet platform for virtual CAD transfers. It is a backend-first portfolio project demonstrating transactional consistency, double-entry accounting, concurrency control and idempotent money operations. No real money, banks or payment providers are involved.

### Project status

Implementation update: 17 November 2026.

Documentation baseline: 15 October 2026, based on **FinCore PRD MVP v1.0**, dated 14 October 2026. Requirements and proposed designs below are not claims of implemented functionality.

The backend implements authentication, sessions, wallets, sandbox funding, transfers,
ledger/history/balance queries, Redis request limits, owner freeze/unfreeze and
read-only reconciliation. Root Docker Compose runs frontend, API, email worker,
maintenance, PostgreSQL, Redis and migrations; see [VPS deployment](docs/deployment.md). The Next.js frontend
in `frontend/` is connected to the API through a server-side gateway with HttpOnly
session cookies; see [local integration setup](frontend/README.md).
GitHub Actions configuration checks backend coverage, frontend and container builds.
An actual VPS deployment and SES delivery on a production domain remain to be verified.

### MVP

The [approved scope update of 16 October 2026](docs/scope-update-2026-10-16.md) supersedes the original single-wallet restriction and adds five-section navigation and a profile. Backend implementation details are documented in backend/README.md.

- Email confirmation registration, confirmation resend, login, rotating refresh sessions and logout.
- Multiple named CAD wallets per user, displayed as cards, with transfers between distinct wallets including the user’s own wallets.
- Operator-authorized sandbox funding and synchronous P2P transfers.
- Immutable double-entry ledger with an atomic balance projection.
- Idempotent money-changing requests and cursor-paginated history.
- Owner/participant authorization and audit trails.

Cards, real payments, FX, fees, refunds, holds, recurring transfers, KYC, analytics/export and a public admin panel are outside MVP.

### Stack

Backend: Python 3.13+, FastAPI, Pydantic, SQLAlchemy, asyncpg, Alembic, Uvicorn and
redis-py, managed with Poetry. PostgreSQL stores financial data; Redis enforces
request limits. Frontend: Next.js App Router, React, TypeScript, Tailwind CSS,
Lucide, next-themes and Zod. See the [frontend README](frontend/README.md).

### Run the connected frontend

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000 after starting the backend and email worker. Register,
confirm your email through local Mailpit, and sign in. Wallets, transfers, history,
sessions and passwords use the real API. See [frontend documentation](frontend/README.md)
for connection settings, sandbox operator permissions and end-to-end checks.

### Run the backend locally

Prerequisites: Python compatible with `backend/pyproject.toml` and Poetry installed.

```bash
cd backend
poetry install
cp .env.example .env
# Configure credentials, then start PostgreSQL/Redis and apply migrations.
make infra
poetry run alembic upgrade head
poetry run uvicorn backend.main:app --app-dir src --reload
```

API prefix is `/v1`. `/health` and `/health/live` check process liveness;
`/health/ready` checks PostgreSQL and Redis. RU/EN documentation and full local
setup are described in [backend/README.md](backend/README.md). Run the outbox worker
separately to deliver registration/reset emails.

### Docker on a VPS

From the repository root, copy `.env.example` to `.env`, configure database/JWT
secrets and SES SMTP, then run:

```bash
docker compose up -d --build --wait
```

Frontend is bound to `127.0.0.1:3000`; API, PostgreSQL and Redis have no published ports.
Set the public HTTPS origin and independent proxy secret, then configure your reverse
proxy to overwrite the required ingress headers. Migrations complete before application
services start. See [deployment instructions](docs/deployment.md)
for health checks, logs, updates and optional local Mailpit. Nginx is configured
by the project owner separately; backups and monitoring services are not provisioned.

### Documentation

Start with the [documentation index](docs/README.md).

- [Architecture](docs/architecture.md) and [data model / ERD](docs/data-model.md)
- [Target API contract and errors](docs/api.md)
- [Financial invariants](docs/invariants.md) and [acceptance plan](docs/test-plan.md)
- [Frontend specification](docs/frontend-spec.md)
- [Open decisions](docs/decisions.md) and [delivery plan](docs/delivery-plan.md)
- [ADR-001: Ledger](docs/adr/ADR-001-ledger.md)
- [ADR-002: Idempotency](docs/adr/ADR-002-idempotency.md)

### Planned demo

Seed synthetic Alice and Bob users and a separate sandbox operator. The operator credits Alice with CAD 500.00; Alice transfers CAD 100.00 to Bob. Expected balances: Alice CAD 400.00, Bob CAD 100.00. Retrying the same transfer request with the same idempotency key must return the original result without another debit. See the [test plan](docs/test-plan.md) for rejection, timeout and concurrency scenarios.

### Release requirements

The [CI workflow](.github/workflows/ci.yml) runs on pushes, pull requests and manual
dispatch. It enforces 91% backend line/branch coverage on Python 3.13/3.14 with real
PostgreSQL, Redis and Mailpit, rejects skipped tests, checks the frontend, runs browser
journeys and verifies the full production Docker stack. See [CI details](docs/ci.md)
and the [17 November verification report](docs/test-report-2026-11-17.md).
Reports are retained for 14 days. Configure branch protection separately to require
**CI required checks** before merging. No deployment or publication is automatic.

Service-data cleanup runs immediately on maintenance container startup and then daily.
It retains full idempotency rows for at least seven days and preserves compact permanent
replay receipts so old pending money requests cannot execute twice. See
[maintenance](docs/maintenance.md) for policy, dry runs and rollback constraints.

Financial acceptance tests must pass against real PostgreSQL, including rollback, reconciliation and concurrent spending tests. Publish reproducible setup, synthetic seed data, CI results and a test report. Frontend checks must cover expired sessions, authorization boundaries, exact money input and safe retries. See [delivery gates](docs/delivery-plan.md).

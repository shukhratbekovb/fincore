# Application backlog: use cases и queries

Срез кода: 14 ноября 2026. Область: текущий backend FinCore, денежные операции
и согласованные экраны «Главная / Кошельки / Перевод / История / Профиль».

Фактическое состояние сверено с `backend/src/backend/application` и routers.
Старые документы описывают целевую архитектуру и местами устарели: в коде prefix
`/v1`, поддерживаются несколько валют и default USD, auth уже реализован.
Этот план не меняет действующие endpoints или контракты.

**Статусы:** «Есть» — обработчик и HTTP endpoint присутствуют; «Разработать» —
application-сценария ещё нет; «Доработать» — расширение существующего сценария;
«Опционально» — предложение за пределами обязательной ближайшей работы.
Наличие кода не означает аудит production readiness.

**Приоритеты:** P0 — безопасное выполнение денежных операций; P1 — завершение
чтения, интерфейса и проверки финансовой целостности; P2 — последующие улучшения.
Команды transfer/sandbox и шесть пользовательских financial queries подключены
к HTTP, SQLAlchemy UoW и PostgreSQL. Остальные будущие сценарии явно отмечены ниже.

Query — также application use case, но только для чтения. Суффикс `UseCase`
ниже обозначает команды, `Query` — чтение; это соглашение об именовании.

## 1. Уже реализованные команды — повторно разрабатывать не нужно

Все пути в таблицах включают действующий prefix `/v1`.

| Use case | HTTP | Вход | Результат / изменение |
|---|---|---|---|
| `RegisterUserUseCase` | `POST /v1/auth/register` | `username`, `email` | `user_id`; PENDING_CONFIRMATION user, challenge и письмо через transactional outbox |
| `ConfirmUserUseCase` | `POST /v1/auth/confirm` | `token`, новый пароль | ACTIVE user с password hash; challenge использован; 204 |
| `LoginUserUseCase` | `POST /v1/auth/login` | `username`, пароль; IP и User-Agent из server context | Access/refresh pair; новая сессия |
| `RefreshSessionUseCase` | `POST /v1/auth/refresh` | Refresh token; IP/User-Agent | Новая пара, ротация refresh; повторное использование отзывает сессию |
| `LogoutUserUseCase` | `POST /v1/auth/logout` | Refresh token | Отзыв соответствующей сессии; 204 |
| `ChangePasswordUseCase` | `POST /v1/auth/change-password` | Actor из JWT, текущий и новый пароль | Новый hash, отзыв всех сессий; 204 |
| `RequestPasswordResetUseCase` | `POST /v1/auth/password-reset/request` | `email` | Для подходящей учётной записи — challenge и письмо; общий ответ 202 |
| `ConfirmPasswordResetUseCase` | `POST /v1/auth/password-reset/confirm` | Reset token | Генерация и смена пароля, отзыв сессий и reset links; новый пароль возвращается один раз после commit |
| `RemoveSessionUseCase` | `DELETE /v1/users/me/sessions/{session_id}` | Actor из JWT, `session_id` | Отзыв своей сессии; отсутствующая/чужая — одинаковый 404 |
| `RemoveAllSessionsUseCase` | `DELETE /v1/users/me/sessions` | Actor из JWT | Отзыв всех своих сессий; 204 |
| `CreateWalletUseCase` | `POST /v1/wallets` | Actor из JWT, `name`, `currency` | `wallet_id`; Wallet, нулевой WalletBalance и LIABILITY LedgerAccount одним commit |
| `RenameWalletUseCase` | `PATCH /v1/wallets/{wallet_id}` | Actor, `wallet_id`, новое имя | Имя своего незакрытого кошелька; 204 |
| `CloseWalletUseCase` | `POST /v1/wallets/{wallet_id}/close` | Actor, `wallet_id` | Закрытие своего кошелька и ledger account при нулевом балансе; история остаётся; 204 |

Отзыв сессии сейчас прекращает refresh; уже выданный access JWT действует до
истечения TTL. Таблица не обещает немедленного отзыва access tokens.

## 2. Уже реализованные queries

| Query | HTTP | Вход / scope | Результат | Дальнейшая работа |
|---|---|---|---|---|
| `GetCurrentUserQuery` | `GET /v1/users/me` | Actor из JWT | `UserDTO`: ID, username, email, created_at | Право sandbox-оператора хранится отдельно и выдаётся через provisioning CLI |
| `GetUserActiveSessionsQuery` | `GET /v1/users/me/sessions` | Actor, server clock | Список своих неотозванных и неистёкших сессий, IP/UA и даты | Новая query не нужна |
| `GetMyWalletsQuery` | `GET /v1/wallets` | Actor; currency/status/sort_by | Список `WalletDTO` с балансом | P1: добавить пагинацию при росте списка; сейчас возвращается весь список |
| `GetWalletQuery` | `GET /v1/wallets/{wallet_id}` | Actor, wallet_id; owner ограничен в SQL | Свой `WalletDTO` с балансом | Новая query для тех же полей не нужна |

## 3. Новые обязательные команды

`CreateTransferUseCase` подключён к POST /v1/transfers: DTO, проверки,
идемпотентность, SQL locks, journal, проекции и replay result в одной транзакции.
Текущий результат содержит только `transfer_id`; расширенный result в таблице —
предлагаемый будущий контракт.
Подробности: [application/transfer/README](../backend/src/backend/application/transfer/README.md).

`CreateSandboxTopUpUseCase` подключён к POST /v1/sandbox/top-ups: обязательная
server-side проверка оператора, выключенный по умолчанию sandbox,
funding lookup, идемпотентность, проводки и один commit. Текущий result — top_up_id.
SQL permission reader, provisioning CLI, настройки и HTTP wiring реализованы:
[application/sandbox_top_up/README](../backend/src/backend/application/sandbox_top_up/README.md).

| Приоритет / статус | Use case / модуль | Предлагаемый HTTP | Команда | Результат | Основные проверки | Атомарные изменения |
|---|---|---|---|---|---|---|
| P0 / Есть | `CreateTransferUseCase` / `application/transfer` | `POST /v1/transfers` | Actor из JWT; sender_wallet_id, receiver_wallet_id, amount_minor, currency; idempotency_key из header | Сейчас `CreateTransferResult(transfer_id)`; расширение до ID, итогового status, суммы, валюты, кошельков и дат — предложение | Actor активен и владеет sender; кошельки существуют, разные, допускают операцию; валюты совпадают; сумма положительна и в пределах лимита; средств достаточно; credit не переполняется; ключ соответствует payload | Transfer + один LedgerTransaction с entries + debit/credit двух WalletBalance + replay result; один commit |
| P0 / Есть | `CreateSandboxTopUpUseCase` / `application/sandbox_top_up` | `POST /v1/sandbox/top-ups` | Actor-operator из JWT; wallet_id, amount_minor, currency; idempotency_key | Сейчас `CreateSandboxTopUpResult(top_up_id)`; расширенный DTO — предложение | Sandbox включён; серверная capability оператора; кошелёк допускает входящее движение; валюты/лимиты; нет переполнения; существует подходящий funding account; ключ соответствует payload | SandboxTopUp + funding DEBIT / wallet CREDIT journal + credit WalletBalance + replay result; один commit |

Actor нельзя брать из произвольного `user_id`/`initiated_by_user_id` тела запроса.
Пополнение выполняет оператор, поэтому владение целевым кошельком не является
заменой проверки его полномочий. Публичное самопополнение не предусмотрено.

Для одного владельца разрешён перевод между разными wallets. Отдельный
`TransferBetweenMyWalletsUseCase` не нужен. Конвертации валют здесь нет.

### Обязательная последовательность денежных команд

| Шаг | Что сделать | Зачем |
|---|---|---|
| 1 | Проверить формат команды, аутентификацию и полномочия; начать UoW | Не сохранять replay-снимки ошибок авторизации как денежную операцию |
| 2 | Захватить idempotency context с UNIQUE(actor, operation_scope, key), сравнить hash бизнес-payload | Тот же ключ/payload возвращает исходный результат; другой payload — конфликт |
| 3 | Заблокировать затрагиваемые строки в едином для всех команд порядке | Переводы, закрытие, freeze/unfreeze и пополнения не должны обходить проверки друг друга |
| 4 | Под блокировками повторно проверить actor/права, статусы, currencies, лимиты, остатки и overflow | Предварительная проверка до блокировки не обеспечивает корректность |
| 5 | Создать operation, изменить проекции, вызвать complete и построить journal в памяти с одним now | Domain-фабрики журнала принимают COMPLETED; это ещё не commit |
| 6 | Сохранить operation, весь journal, проекции и replay result | Нет отдельных commits для списания, зачисления или результата идемпотентности |
| 7 | Один commit и возврат результата | Потерянный ответ восстанавливается повтором с тем же ключом |
| Отказ | Устойчивый бизнес-отказ: REJECTED + replay, без journal и изменений баланса, если принимаем эту политику | Точная политика хранения REJECTED требует решения до реализации |
| Сбой | Transient error / исключение: rollback всей попытки | Не превращать технический сбой в постоянный бизнес-отказ |

Порядок блокировок нужно закрепить совместно с существующими командами:
если блокируются users — по UUID; затем все wallets по UUID; затем balances
по wallet UUID; затем accounts по согласованному порядку. Учитывать уже имеющийся
порядок wallet → balance → account при CloseWallet. Все команды должны соблюдать
одну иерархию; нельзя брать вторую wallet-строку после balance-строки первой.
Создание/сериализация idempotency context предшествует этим финансовым locks.

## 4. Новые пользовательские queries

`GetTransferQuery` и `GetMyTransfersQuery` подключены к HTTP и SQL reader:
DTO, filters, обязательный scope actor, PageDTO и подписанная cursor pagination.
Подробности в
[application/transfer/README](../backend/src/backend/application/transfer/README.md).

Четыре оставшиеся пользовательские query также подключены к SQL и HTTP:
история wallet, общая история, сводный баланс и баланс wallet.
Политики и контракты описаны в
[history/README](../backend/src/backend/application/history/README.md) и
[wallet_balance/README](../backend/src/backend/application/wallet_balance/README.md).

Списковые DTO возвращаются как `PageDTO(items, next_cursor)`.
Суммы — minor units, в новых HTTP responses десятичными строками для точности
JavaScript; значения разных валют не суммируются в одно число.

| Приоритет / статус | Query / модуль | Предлагаемый HTTP | Вход и фильтры | Результат | Доступ / правила чтения |
|---|---|---|---|---|---|
| P1 / Есть | `GetTransferQuery` / `transfer` | `GET /v1/transfers/{transfer_id}` | Actor, transfer_id | Один `TransferDTO`, включая итоговый status/rejection_code | Sender или receiver через wallets; отсутствующий и чужой — одинаковый 404; без чужих остатков, email и IP |
| P1 / Есть | `GetMyTransfersQuery` / `transfer` | `GET /v1/transfers` | Actor; wallet_id?, currency?, status?, direction?, from/to?, cursor?, limit? | Страница `TransferDTO` | Sender OR receiver = actor; свой внутренний перевод один раз; ownership не является опциональным фильтром |
| P1 / Есть | `GetWalletTransactionsQuery` / `wallet` | `GET /v1/wallets/{wallet_id}/transactions` | Actor, wallet_id; kind?, currency?, direction?, posted_from/to?, cursor?, limit? | Страница `WalletTransactionDTO`: journal ID, source type/ID, amount, currency, direction, posted_at | Только свой wallet, в том числе закрытый; только проведённые движения; отдельная сторона journal для выбранного wallet |
| P1 / Есть | `GetMyTransactionsQuery` / `history` | `GET /v1/users/me/transactions` | Actor; wallet_id?, currency?, kind?, direction?, posted_from/to?, cursor?, limit? | Общая страница `TransactionDTO`: transfer/top-up, кошельки, сумма, direction, posted_at | Только операции своих wallets; внутренний перевод один раз как INTERNAL, а при wallet filter — INCOMING/OUTGOING выбранного wallet; REJECTED не смешивать с проведёнными движениями |
| P1 / Есть | `GetMyBalanceSummaryQuery` / `wallet` | `GET /v1/users/me/balances` | Actor; currency? | `BalanceSummaryDTO`: totals по currency, posted_minor, available_minor, spendable_minor, as_of | Все свои wallets в posted/available, только ACTIVE в spendable; один snapshot; пропавший balance/account — ошибка целостности |
| P1 / Есть | `GetWalletBalanceQuery` / `wallet` | `GET /v1/wallets/{wallet_id}/balance` | Actor, wallet_id | `WalletBalanceDTO`: wallet_id, currency, posted_minor, available_minor, spendable_minor, version, updated_at, as_of | Owner scope; available=posted пока нет holds; spendable=0 у FROZEN/CLOSED; updated_at берётся у balance, а не Wallet |

`GetMyTransfersQuery` отвечает на вопрос об операциях перевода, включая
REJECTED, если они сохраняются. History queries показывают только фактические
движения по журналам. Это разные наборы данных, их не следует незаметно смешивать.

Предлагаемый контракт пагинации: limit=20, max=100; порядок
`(created_at DESC, id DESC)` для transfers и `(posted_at DESC, id DESC)` для history;
keyset cursor содержит последний tuple и привязан к actor, типу списка и фильтрам.
Невалидный/несовместимый cursor — понятная ошибка валидации. Cursor не предоставляет
полномочий: owner scope применяется в SQL на каждой странице. Это стабильный порядок,
а не обещание общего snapshot между отдельными HTTP-запросами.

## 5. Служебная query для проверки денег

| Приоритет / статус | Query | Запуск / вход | Результат | Обязательные проверки |
|---|---|---|---|---|
| P1 / Есть, служебная CLI | `ReconcileLedgerQuery` / `application/ledger_transaction` | Внутренняя CLI/job, scope wallets/currency; защищённый доступ, не пользовательский HTTP | `ReconciliationReportDTO`: checked_at, scope, количество проверок, отклонения | В одном согласованном snapshot: WalletBalance = CREDIT−DEBIT LIABILITY; journals balanced и >=2 entries; currencies account/entry/journal совпадают; source link уникален; COMPLETED имеет ровно один journal, REJECTED — ни одного; account/balance не пропали |

Reconciliation ничего автоматически не исправляет. Крупный отчёт можно отдавать
потоком/с ограниченным числом примеров, сохраняя общий счётчик отклонений; чтение
разными запросами требует общей транзакции с подходящим snapshot.

## 6. Опциональные сценарии — не обязательства текущего MVP

| Приоритет | Use case / query | Зачем | Что потребуется перед реализацией |
|---|---|---|---|
| Есть | `FreezeWalletUseCase` | Owner-only POST /v1/wallets/{wallet_id}/freeze, 204 идемпотентно | Активный owner; запрещает новые входящие/исходящие движения; CLOSED409; баланс/account не меняются |
| Есть | `UnfreezeWalletUseCase` | Owner-only POST /v1/wallets/{wallet_id}/unfreeze, 204 идемпотентно | Только пользовательская заморозка: административной модели freeze пока нет; CLOSED409; общие locks |
| P2 | `ResendRegistrationConfirmationUseCase` | Повторное письмо без повторной регистрации | Rate limit, одинаковый публичный ответ, инвалидировать прежний challenge, новый challenge+outbox одним commit |
| P2 | `GetSandboxTopUpQuery` | Детали пополнения по ID | Владелец целевого wallet либо уполномоченный operator; отдельный public DTO не раскрывает внутренние данные оператора |
| P2 | `GetSandboxTopUpsQuery` | Список пополнений для оператора | Server-side capability, scope, фильтры, pagination; это не публичный список всех клиентов |
| P2 | `GetOperationResultQuery` | Восстановить неизвестный результат после timeout/reload | Отдельный согласованный контракт: actor+scope+key, срок хранения, безопасный result; после удаления replay record отсутствие записи не означает отсутствие движения |

Админские списки пользователей/кошельков, изменение профиля/email, закрытие
пользователя, валютный обмен, комиссии, holds, отмена и возвраты здесь не объявлены
обязательными: для них нужны отдельные продуктовые правила и модель доступа.

## 7. Общие механизмы и инфраструктура — это не отдельные публичные use cases

| Компонент | Назначение / предлагаемый интерфейс | Зависимые сценарии | Состояние |
|---|---|---|---|
| `ITransferRepository` | add + получение operation; без независимого commit | Создание перевода | Разработать |
| `ISandboxTopUpRepository` | add + получение operation; хранить initiated_by_user_id | Sandbox command | Контракт add есть; SQL и чтение разработать |
| `ILedgerTransactionRepository` | append целого aggregate с entries; get с полным набором entries; без update/delete | Оба денежных сценария | Разработать; отдельный публичный CRUD LedgerEntry не нужен |
| `IIdempotencyRepository` + coordinator | Захват ключа, payload hash, bounded ожидание конкурента, сохранение replay; общая SQL-транзакция UoW | Оба денежных сценария | Разработать; не отдельная независимая транзакция/Redis-only cache |
| `LedgerPostingService` | Общая application-логика построения journal и изменения проекций; без своего commit или вложенной UoW | Оба денежных сценария | Разработать; не дублировать проверки domain-фабрик |
| `ITransferReader` | Owner/participant-scoped read projections | GetTransfer / GetMyTransfers | Разработать |
| `ITransactionHistoryReader` | Проекции journal+source+wallets без N+1 и дубликатов | История wallet и общая история | Есть application и scoped SQL reader |
| `IWalletBalanceReader` | Точный snapshot баланса и totals по валютам | Balance / Summary | Есть DTO/application и SQL reader; summary одним statement |
| `ILedgerReconciliationReader` | Snapshot-отчёт по ledger, balances и источникам | ReconcileLedgerQuery | Есть SQL reader: один READ ONLY SELECT, полные counts, ограниченные примеры |
| Funding accounts | Найти единственный `SYS:SIM_FUNDING:{currency}`; provisioning через seed/migration/CLI | Sandbox command | Есть SQL lookup, миграция funding accounts и provisioning CLI |
| Operator authorization | Capability/role из доверенного серверного источника; не флаг request body | Sandbox и ops queries | Есть SQL permission reader, sandbox_operators и provisioning CLI; grant/revoke сериализуются на user row |
| SQL models / migrations / privileges | Transfer, SandboxTopUp, journal, entries, replay; FK/UNIQUE/CHECK, совместимость currencies, запрет правок ledger, posting enforcement | Всё денежное ядро | Модели/миграции и financial guards есть; отдельные DB roles/privileges остаются задачей |
| UoW wiring | Добавить repositories и readers, использующие ту же AsyncSession | Все новые handlers | Есть repositories/readers с общей AsyncSession; `_Readers` отделён от `_Repositories` |
| Outbox worker | Надёжно доставлять письма после commit | Регистрация и password reset | Уже есть `OutboxProcessor`; второй use case отправки тех же писем не нужен |
| Readiness | `/health/ready` с проверкой critical dependencies и timeout | Эксплуатация | Есть PostgreSQL/Redis probes с timeout, 200/503; /health/live и /health остаются liveness |

Отдельные `CreateLedgerEntryUseCase`, `UpdateLedgerTransactionUseCase`,
`CreditWalletUseCase` и `DebitWalletUseCase` не нужны для текущего продукта:
они позволили бы обходить бизнес-операцию и общую атомарность. Отдельный
`CreateLedgerAccountUseCase` для пользовательского счёта тоже не нужен —
этот шаг уже входит в CreateWalletUseCase.

## 8. DTO и правила контрактов, которые нужно определить

| DTO / правило | Минимальный состав / решение |
|---|---|
| `CreateTransferCommand` | actor_user_id, sender_wallet_id, receiver_wallet_id, amount_minor, currency, idempotency_key; server context отдельно от user-controlled payload |
| `CreateSandboxTopUpCommand` | actor_user_id, wallet_id, amount_minor, currency, idempotency_key; actor становится initiated_by_user_id |
| `TransferDTO` / `TransferResult` | ID, sender/receiver wallet IDs, amount_minor, currency, status, rejection_code?, created_at, completed_at?; публичные данные без чужих балансов/секретов |
| `SandboxTopUpDTO` / result | ID, wallet_id, amount_minor, currency, status, rejection_code?, created_at, completed_at?; operator metadata только в разрешённой проекции |
| `WalletTransactionDTO` | journal ID, source_type/source_id, wallet_id, counterparty_wallet_id?, direction, amount_minor, currency, posted_at |
| `TransactionDTO` | journal ID, source_type/source_id, source/destination wallet IDs по доступному контракту, direction INCLUDING INTERNAL, amount_minor, currency, posted_at |
| `PageDTO[T]` | items: list[T], next_cursor: str или null; без обязательного дорогого total_count |
| `BalanceSummaryDTO` | totals: list значений по currency с posted_minor/available_minor, as_of; нельзя складывать USD и UZS |
| BIGINT ↔ JSON | Domain допускает signed BIGINT; frontend JS number не представляет весь этот диапазон точно. Выбрать строковые minor units либо согласовать безопасные API-лимиты, включая агрегаты; новые financial responses отдают строки; прежний WalletResponse.balance_minor остаётся числом |
| Идемпотентность | Scope actor+operation+key; canonical business payload hash; тот же результат для replay; retention минимум 24h по текущему ADR; поведение после TTL отдельно |
| Замороженный wallet | Предложение: запрет входящих и исходящих, но дать читать историю; утвердить до денег |
| REJECTED и HTTP | Утвердить сохранение устойчивых бизнес-отказов и их HTTP status/body. Успех COMPLETED — 201; отказ не выдавать как успешное движение |
| Лимиты и роли | Конкретные max amount/top-up лимиты, rate limits, operator capability, sandbox enabled — до денежных endpoints |

## 9. Порядок разработки и критерии готовности

| Этап | Что реализовать | Проверяемый результат |
|---|---|---|
| 1 | Зафиксировать лимиты, operator capability, frozen/rejection policy, JSON amounts, cursor и idempotency conflicts | Согласованные commands, results, errors и доступ без скрытых допущений |
| 2 | SQL schema, append-only ledger, repos/UoW, funding provisioning, idempotency и общий posting path | Из runtime DB role невозможно незаметно создать половину journal или изменить проведённую запись; rollback откатывает всё |
| 3 | CreateSandboxTopUpUseCase | Оператор добавляет виртуальные средства; один journal; повтор ключа не добавляет деньги; неоператор получает отказ |
| 4 | CreateTransferUseCase | Разные owners и свои разные wallets; корректные остатки; нет overdraft; один journal на успешную операцию |
| 5 | ReconcileLedgerQuery и обязательные concurrency/fault-injection проверки | Совпадают ledger и projections; replay после потерянного ответа; встречные переводы; конкурентное списание; 100 параллельных команд |
| 6 | GetTransfer/GetMyTransfers и wallet history | ACL, стабильная cursor pagination, закрытые wallets читаются, REJECTED не показывается как движение |
| 7 | Общая history + balance summary; balance endpoint при сохранении этого контракта | Внутренний перевод 100 из 500: остатки 400/100, общий итог 500, одна строка общей истории, правильные стороны в wallet history |
| 8 | HTTP wiring, dependencies, RU/EN OpenAPI, readiness и end-to-end проверки | Реальный путь router → use case → PostgreSQL → DTO, ошибки/no-store и права совпадают с документацией |

Unit-тесты новых сущностей уже есть. Они не заменяют PostgreSQL-проверки locks,
ограничений, привилегий, единственного posting, идемпотентности и атомарного rollback.

## Источники внутри проекта

- [Application-код](../backend/src/backend/application/)
- [Текущие routers](../backend/src/backend/presentation/api/v1/routers/)
- [Доменный журнал](../backend/src/backend/domain/ledger_transaction/entities.py)
- [Согласованный scope](scope-update-2026-10-16.md)
- [Инварианты](invariants.md)
- [ADR: ledger](adr/ADR-001-ledger.md)
- [ADR: идемпотентность](adr/ADR-002-idempotency.md)
- [Открытые решения](decisions.md)


## Эксплуатация на VPS

Корневой Docker Compose, middleware JSON-логов и health endpoints описаны в
[deployment.md](deployment.md). API/worker используют общий образ, миграции —
отдельный job. Nginx пользователь настраивает сам; резервное копирование
и внешние мониторинговые сервисы в текущую задачу не входят.

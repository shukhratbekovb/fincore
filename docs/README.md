# Документация FinCore MVP / FinCore MVP documentation

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

Обновлено: 17 ноября 2026. Источник требований: [PRD MVP v1.0](../FinCore_PRD_MVP_v1.0%20%281%29.pdf), 14 октября 2026, 11 страниц.

Архитектура, модель данных, API, deployment и maintenance описывают текущую реализацию. Исходные PRD и октябрьские спецификации сохраняют исторический scope; фактический контракт задают код и RU/EN OpenAPI. Оставшиеся решения перечислены отдельно.

| Документ                                        | Назначение                                                                         |
| ----------------------------------------------- | ---------------------------------------------------------------------------------- |
| [README проекта](../README.md)                  | Описание RU/EN, фактический статус и инструкции запуска                            |
| [Архитектура](architecture.md)                  | Границы модулей, транзакции, безопасность                                          |
| [Модель данных](data-model.md)                  | ERD, поля, ограничения и связи                                                     |
| [API](api.md)                                   | Endpoints, примеры, ошибки и пробелы контракта                                     |
| [Инварианты](invariants.md)                     | Денежные гарантии, reconciliation и демонстрации                                   |
| [ADR-001](adr/ADR-001-ledger.md)                | Подход к ledger                                                                    |
| [ADR-002](adr/ADR-002-idempotency.md)           | Идемпотентность и повтор после тайм-аута                                           |
| [Спецификация фронтенда](frontend-spec.md)      | Карта экранов, сценарии и состояния                                                |
| [План проверок](test-plan.md)                   | Acceptance criteria backend и frontend                                             |
| [Реестр решений](decisions.md)                  | Что необходимо согласовать перед интеграцией                                       |
| [План поставки](delivery-plan.md)               | Этапы, зависимости и Definition of Done                                            |
| [VPS Docker](deployment.md)                     | Полный стек, ingress/IP, обновления и health                                       |
| [Обслуживание](maintenance.md)                  | Retention, dry-run, daily cleanup и permanent replay receipts                      |
| [Проверки 15 ноября](test-report-2026-11-15.md) | Локальные результаты и границы проверки                                            |
| [Use cases и queries](use-cases-and-queries.md) | Срез backend на 11 ноября 2026, подробный application backlog и порядок разработки |

### Согласованное изменение

[Решения от 16 октября 2026](scope-update-2026-10-16.md) заменяют ограничение одного кошелька: несколько CAD-кошельков и пять разделов, включая Перевод и Профиль. Исходный PDF сохранён как baseline.

### Текущее состояние frontend

Next.js подключён к API: авторизация, кошельки, переводы, история и сессии.
[Инструкция интеграции и запуска](../frontend/README.md) описывает актуальные сценарии;
[первый отчёт](frontend-implementation.md) сохранён как история исходного demo.

### Порядок работы

1. Запустить локальный стек по frontend/README.md либо production Compose по deployment.md.
2. При изменении API обновить RU/EN схемы, примеры, frontend и тесты вместе.
3. Выполнить тесты с выделенными PostgreSQL/Redis/Mailpit и проверить CI.
4. Для публичного релиза завершить реальные Nginx/HTTPS/SES и VPS-проверки из плана поставки.

При изменении контракта обновлять связанные документы и тесты в одной поставке. PRD остаётся исходной baseline; предложения в этом комплекте не меняют его без явного решения.

Актуальная настройка [CI](ci.md) и [отчёт проверок 17 ноября](test-report-2026-11-17.md) включают Python 3.13/3.14, browser E2E и production Docker-проверки.

<a id="en"></a>

## English

Updated: 17 November 2026. Requirements source: [PRD MVP v1.0](../FinCore_PRD_MVP_v1.0%20%281%29.pdf), 14 October 2026, 11 pages.

Architecture, data model, API, deployment and maintenance describe the current implementation. The original PRD and October specifications retain their historical scope; code and RU/EN OpenAPI define the actual contract. Outstanding decisions are listed separately.

| Document                                          | Purpose                                                                                        |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| [Project README](../README.md)                    | Russian/English overview, actual status and startup instructions                               |
| [Architecture](architecture.md)                   | Module boundaries, transactions and security                                                   |
| [Data model](data-model.md)                       | ERD, fields, constraints and relationships                                                     |
| [API](api.md)                                     | Endpoints, examples, errors and contract gaps                                                  |
| [Invariants](invariants.md)                       | Financial guarantees, reconciliation and demonstrations                                        |
| [ADR-001](adr/ADR-001-ledger.md)                  | Ledger approach                                                                                |
| [ADR-002](adr/ADR-002-idempotency.md)             | Idempotency and retry after a timeout                                                          |
| [Frontend specification](frontend-spec.md)        | Screens, flows and states                                                                      |
| [Test plan](test-plan.md)                         | Backend and frontend acceptance criteria                                                       |
| [Decision register](decisions.md)                 | Agreements needed before integration                                                           |
| [Delivery plan](delivery-plan.md)                 | Stages, dependencies and Definition of Done                                                    |
| [VPS Docker](deployment.md)                       | Full stack, ingress/IP, updates and health                                                     |
| [Maintenance](maintenance.md)                     | Retention, dry runs, daily cleanup and permanent replay receipts                               |
| [15 November checks](test-report-2026-11-15.md)   | Local results and verification limits                                                          |
| [Use cases and queries](use-cases-and-queries.md) | Backend snapshot as of 11 November 2026, detailed application backlog and implementation order |

### Approved scope change

[Decisions of 16 October 2026](scope-update-2026-10-16.md) replace the single-wallet restriction: multiple CAD wallets and five sections, including Transfer and Profile. The original PDF remains the baseline.

### Current frontend status

Next.js is connected to the API: authentication, wallets, transfers, history and sessions.
The [integration and startup guide](../frontend/README.md) describes current flows;
the [first report](frontend-implementation.md) is retained as the history of the original demo.

### Working process

1. Start the local stack using frontend/README.md or production Compose using deployment.md.
2. When changing the API, update RU/EN schemas, examples, frontend and tests together.
3. Run tests with dedicated PostgreSQL/Redis/Mailpit and check CI.
4. For a public release, complete the real Nginx/HTTPS/SES and VPS checks from the delivery plan.

Update related documents and tests together when the contract changes. The PRD remains the original baseline; proposals in this documentation do not change it without an explicit decision.

The current [CI configuration](ci.md) and [17 November verification report](test-report-2026-11-17.md) cover Python 3.13/3.14, browser E2E and production Docker checks.

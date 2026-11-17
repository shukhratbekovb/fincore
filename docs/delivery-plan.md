# План поставки и Definition of Done

Состояние на 17 ноября 2026. Источник scope — [решение от 16 октября](scope-update-2026-10-16.md). Реализованная локальная функциональность и опубликованный production release учитываются отдельно.

| Этап                   | Состояние                                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------------------------ |
| M1 Foundation          | Auth, email confirmation/resend/reset, сессии, миграции и тестовое окружение реализованы               |
| M2 Wallets             | Создание, чтение, rename/close/freeze/unfreeze, номера и балансы реализованы                           |
| M3 Ledger              | Double-entry posting, sandbox, атомарные проекции и read-only reconciliation реализованы               |
| M4 Transfers           | Переводы по номеру получателя, idempotency/receipts, history/cursors и Redis budgets реализованы       |
| M5 Release preparation | Frontend интегрирован; Docker всего стека, CI workflow и maintenance подготовлены и проверены локально |
| M5 Published release   | VPS/Nginx/HTTPS/SES, первый Actions run, demo URL и performance report ещё не подтверждены             |

## Проверено

- [x] Backend и frontend используют реальный API, PostgreSQL, Redis и outbox.
- [x] Production образы backend/frontend собираются, Compose запускается на отдельной чистой базе.
- [x] Отдельные dev и production Compose находятся в корне.
- [x] HTTP/OpenAPI документация RU/EN включает resend и все текущие маршруты.
- [x] CLI очистки, daily maintenance, dry-run и защита поздних денежных повторов.
- [x] GitHub Actions workflow с порогом 91%, frontend checks и container smoke test; фактический GitHub run ожидает push.
- [x] [Локальный отчёт проверок](test-report-2026-11-17.md) с результатами и границами доказательств.

## Перед публичным запуском

1. Настроить реальные домен, HTTPS и собственный Nginx по [контракту ingress](deployment.md).
2. Проверить SES на production identity; Mailpit подтверждает локальный транспорт, не доставляемость внешней почты.
3. Отправить изменения на GitHub, получить успешный Actions run и при необходимости сделать его обязательным через branch protection.
4. Проверить обновление на VPS, подготовить воспроизводимые synthetic demo данные и опубликовать URL.
5. Отдельно выполнить измеренный benchmark с описанием нагрузки и ресурсов. Текущий тестовый отчёт не заменяет benchmark.

Текущие ограничения продукта и эксплуатации перечислены в [реестре решений](decisions.md). Все средства в FinCore виртуальные; реальные банки и платёжные провайдеры не подключены.

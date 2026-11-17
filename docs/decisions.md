# Реестр решений и оставшихся вопросов

Обновлено 15 ноября 2026. Таблица описывает текущую реализацию. Исходные предложения октября сохранены в PRD и [scope update](scope-update-2026-10-16.md).

| ID     | Область            | Текущее решение                                                                                                                           |
| ------ | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| D01–02 | Frontend           | Русский адаптивный UI, Next.js App Router/React/TypeScript, Zod, Vitest и Playwright                                                      |
| D03    | Получатель         | Точный 20-значный номер, resolve возвращает wallet_id, number, currency, owner=username получателя; UUID остаётся в API/URL               |
| D04    | Browser sessions   | Access и refresh в HttpOnly/SameSite=Lax cookies Next.js; Secure в production; gateway проверяет Origin                                   |
| D05/17 | Sandbox operator   | Отдельная серверная таблица разрешений и CLI выдачи; SANDBOX_ENABLED=false по умолчанию                                                   |
| D06    | Ограничения        | Password policy, Redis request budgets и предел одной денежной операции реализованы; дневные лимиты ещё требуют решения                   |
| D07    | Контракты          | Реальные схемы и RU/EN примеры генерируются из FastAPI; [API](api.md)                                                                     |
| D08    | Freeze             | Владелец может заморозить/разморозить кошелёк; новые входящие и исходящие движения запрещены; чтение доступно                             |
| D09    | Отказы операций    | Бизнес-отказ откатывает всю попытку, REJECTED и его replay сейчас не сохраняются                                                          |
| D10    | Конкурирующий ключ | Ожидание блокировки до 2 секунд, затем retryable `409` idempotency_in_progress с тем же ключом/payload                                    |
| D11–12 | История            | source_type/source_id, направления, серверные фильтры и подписанный cursor, сортировка по времени/id                                      |
| D13    | UUID               | uuid4 для внутренних идентификаторов; номер кошелька — отдельный уникальный реквизит                                                      |
| D14    | Деньги в JSON      | Строки minor units; frontend использует bigint                                                                                            |
| D15    | Поздние повторы    | Полные replay records по умолчанию 7 дней и минимум до expires_at; затем постоянные immutable receipts; pending-команды переживают reload |
| D16    | Ledger enforcement | Атомарная UoW, блокировки, constraints и deferred triggers; отдельные ограниченные DB roles пока не подготовлены                          |
| D18    | Auth               | Контракты ошибок, email confirmation, resend, reset и password change реализованы                                                         |
| D19    | Production ingress | Nginx → Next.js → private API, отдельный proxy secret, проверенный X-Real-IP и фиксированный PUBLIC_APP_ORIGIN                            |
| D20    | Retention          | Настраиваемая пачечная очистка в maintenance-контейнере; [политика](maintenance.md)                                                       |

## Оставшиеся решения и проверки

- Продуктовые дневные/месячные лимиты сумм и количества операций, лимит числа кошельков.
- Требуется ли сохранять бизнес-отказы и воспроизводить их по ключу вместо текущего rollback.
- Нужен ли немедленный отзыв access JWT: сейчас отзываются refresh-сессии, уже выпущенный access действует до exp при активном пользователе.
- Production домен, SES identity/доставка и реальная конфигурация Nginx владельца VPS.
- Первый фактический запуск GitHub Actions, branch protection и публичный demo URL.
- Воспроизводимый performance benchmark и dedicated DB privileges.

Резервное копирование и внешние системы мониторинга отложены по решению владельца проекта. Несколько кошельков и переводы между своими разными кошельками поддерживаются; перевод в тот же кошелёк запрещён.

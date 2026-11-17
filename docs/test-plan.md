# План тестирования и приёмки

Дата: 15 октября 2026. Статус всех сценариев: **не выполнены в рамках подготовки документации**. Основание: PRD §14 плюс предложенные frontend acceptance cases.

## Backend acceptance

| ID | Сценарий | Ожидаемый результат |
|---|---|---|
| ACC-01 | Register/login/refresh/logout | Hash пароля, rotation/revocation; invalid/expired/replayed sessions отклоняются |
| ACC-02 | Создать два CAD wallets одному user | Два независимых wallets, каждый с нулевым Balance и liability account; отменяет исходный ACC-02 после scope update |
| ACC-03 | Sandbox top-up 500 CAD | Wallet credit 50000, system asset debit 50000, balance=50000 |
| ACC-04 | Alice→Bob 100 CAD | Alice −10000, Bob +10000, balanced journal |
| ACC-05 | Недостаток средств | Нет posting и изменений balances |
| ACC-06 | Два расхода по 80 из 100 CAD | Максимум один успех; без инфраструктурного fault ровно один |
| ACC-07 | Replay одного ключа | Исходный HTTP status/body, один posting |
| ACC-08 | Тот же ключ, иной payload | 409, без второго движения |
| ACC-09 | Ошибка между debit и credit | Полный rollback всех финансовых изменений |
| ACC-10 | Доступ к чужому wallet/transfer | Нет раскрытия balances/details, server ACL |
| ACC-11 | Reconciliation | Projection равна liability credits−debits |
| ACC-12 | Pagination/filtering | Стабильный порядок, нет дублей/пропусков на fixture; фильтры после определения контракта |
| ACC-13 | Frozen wallet | Запрет отправки/получения по окончательно принятой политике |
| ACC-14 | 100 concurrent randomized transfers | Нет отрицательных balances, balanced journals, conservation |

Дополнительно: unauthorized/disabled sandbox, top-up limits, concurrent same-key delivery, потеря ответа после commit, immutable DB permissions, overflow, валютная несовместимость, перевод в тот же wallet, структурированные ошибки без секретов, readiness при отказе БД. Регистрация не должна автоматически создавать wallet без отдельного решения: PRD задаёт отдельный POST.

Unit tests покрывают чистую валидацию и форматирование; integration/concurrency tests используют реальный PostgreSQL. SQLite и mock repositories не доказывают row locking и transaction semantics.

## Frontend acceptance — предложение

| ID | Сценарий | Ожидаемый результат |
|---|---|---|
| FE-01 | Гость открывает protected route | Login; закрытые данные не отображаются |
| FE-02 | Register/login errors | Ошибки полей/общие доступны, пользовательский ввод не теряется без причины |
| FE-03 | Новый пользователь создаёт wallet | Empty→submitting→wallet 0.00 CAD; создание второго CAD wallet допустимо |
| FE-04 | Money input | 100.00→10000; 0.01→1; отрицательное/0/лишние decimals/range отвергнуты |
| FE-05 | Валидный перевод | Review, один ключ, подтверждение сервера, обновление balance/history |
| FE-06 | Double click и timeout | Нет нового ключа для повторной доставки; unknown outcome не объявляется failure/success |
| FE-07 | Insufficient funds/inactive/перевод в тот же wallet | Понятная причина, нет ложного completed UI |
| FE-08 | Cursor history | Следующая страница, end state, retry, нет дублей в UI; source links корректны |
| FE-09 | Сессия истекла/выход/смена user | Нет refresh loop и утечки предыдущего cache; revocation соблюдён |
| FE-10 | Обычный user открывает sandbox route | Нет operator формы без capability; backend также отклоняет запрос |
| FE-11 | Mobile/keyboard/screen-reader basics | Все действия доступны, focus видим, UUID читаем, нет горизонтального overflow на 320 px |
| FE-12 | Loading/empty/offline/429/503 | Явные состояния, безопасный retry, отсутствие фиктивных данных |

Проверять несколько одновременно истёкших запросов, возврат к форме после ошибки и историю после успешного перевода. Tests frontend с mock API не заменяют integration с фактическим backend.

## Дополнительная приёмка согласованного scope

| ID | Сценарий | Ожидаемый результат |
|---|---|---|
| FE-13 | Пять разделов mobile/desktop | Перевод по центру нижнего меню; те же разделы сбоку на desktop; быстрые действия предвыбирают source |
| FE-14 | Карточки и внутренний перевод | Два CAD wallets, перевод 100 из 500: 400/100, общий баланс 500; в общей истории одна операция, wallet filter показывает своё направление |
| FE-15 | Профиль | Доступные данные пользователя, настройки оформления и выход; нет обещания API редактирования |

Backend: проверить отдельные accounts/balances нескольких wallets, ACL, запрет одинаковых source/target, idempotency и concurrency между своими wallets. Общую историю и баланс проверять по согласованному snapshot/cursor contract.

## Synthetic fixtures

Alice и Bob — активные users с CAD wallets; Carol — дополнительный получатель; отдельный sandbox operator. Добавить frozen/closed wallet, suspended user, чужой transfer. UUID и timestamps фиксировать в tests; credentials генерировать для окружения, не публиковать реальные данные.

Demo baseline: operator→Alice 50000, Alice→Bob 10000, ожидаемые balances 40000/10000. Для race fixtures сбрасывать данные независимо от demo.

## Формат будущего отчёта

- Commit и дата, версии Python/PostgreSQL и test dependencies.
- Команды запуска и конфигурация без секретов.
- Количество passed/failed/skipped; причины skips.
- Результаты ACC и FE, concurrency seed, reconciliation.
- Для benchmark: hardware, dataset, load, warm-up, sample size, p95.

Пустой шаблон не является test report. CI badge, успешные тесты и целевые latency нельзя заявлять до фактического запуска.

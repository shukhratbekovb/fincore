# Денежные инварианты и проверка корректности

Статус: требования PRD §8–9 и план демонстраций, не результаты тестов. Дата: 15 октября 2026.

## Обязательные гарантии

| ID | Инвариант | Доказательство при реализации |
|---|---|---|
| INV-01 | Для journal debits=credits в одной валюте | Суммы grouped entries и тест DB enforcement |
| INV-02 | Валюта entry=account=transaction | Проверка связей и попытка несовместимого posting |
| INV-03 | Posted entry/transaction нельзя изменить или удалить | UPDATE/DELETE под runtime DB role отклонены |
| INV-04 | WalletBalance=credits−debits liability account | Reconciliation каждого wallet |
| INV-05 | Баланс пользователя >=0 | DB constraint и concurrent spend tests |
| INV-06 | COMPLETED transfer имеет один journal, REJECTED — ни одного | Join/count assertions |
| INV-07 | Debit, credit, две проекции и replay result commit/rollback вместе | Fault injection и независимое чтение |
| INV-08 | Amounts положительные BIGINT cents, без overflow | Границы, невалидные значения и суммы |
| INV-09 | История имеет стабильные ID/timestamps, без ручной правки | Replay и immutable checks |
| INV-10 | P2P не меняет сумму средств всех пользователей | До/после batch без top-up |

## Учётные примеры

Перевод CAD 100.00: DEBIT Alice LIABILITY 10000, CREDIT Bob LIABILITY 10000. Баланс Alice уменьшается, Bob увеличивается.

Sandbox CAD 500.00: DEBIT SYS:SIM_FUNDING:CAD ASSET 50000, CREDIT Alice LIABILITY 50000. Эта операция увеличивает сумму пользовательских средств и исключается из проверки P2P conservation.

## Reconciliation

Для каждого wallet найти единственный CAD LIABILITY account. Рассчитать сумму CREDIT amount_minor минус DEBIT amount_minor по проведённым entries; пустой ledger даёт 0. Сравнить с posted_minor в **одном согласованном snapshot БД**. Отсутствующие account/balance или их дубли являются отдельной ошибкой, а не нулевым балансом.

Дополнительно проверить journal с менее чем двумя entries, debits != credits, несовпадение валют, missing/duplicate business links, отрицательные balances и postings для REJECTED. Проверять отдельные journal, а не только общий итог: ошибки разных операций могут взаимно компенсироваться.

Это алгоритм, не исполняемый SQL: окончательные запросы следует добавить вместе с миграциями и фактическими именами таблиц. Reconciliation не должен автоматически исправлять ledger.

## Воспроизводимые демонстрации

### Конкурентное списание

Fixture: Alice 10000 cents, Bob и Carol 0. Через отдельные соединения и barrier одновременно отправить два перевода по 8000 с разными ключами. Ожидается ровно один успех при отсутствии инфраструктурных сбоев; другой — insufficient funds. Alice=2000, суммарный balance=10000, один completed posting, все инварианты соблюдены.

### Потеря ответа после commit

Fixture: Alice 50000, Bob 0. Выполнить перевод 10000 и подавить доставку HTTP-ответа после commit в test harness. Повторить исходный payload/key. Ожидается тот же transfer ID/status/body, Alice=40000, Bob=10000, один journal. Нужна точная точка fault injection после commit.

### Rollback между entries

В test-only hook выбросить исключение после вставки debit до credit. После rollback из другого соединения проверить отсутствие обеих entries/journal/completed transfer и завершённого success replay; balances исходные. Повтор с тем же ключом после устранения fault должен выполнить максимум одну успешную команду. Test hook не должен быть публичным API.

### Встречные переводы

Запустить Alice→Bob и Bob→Alice с достаточными средствами через отдельные соединения. Проверить единый порядок row locks, отсутствие штатного AB-BA deadlock, итоговые balances и ограниченное поведение retry при transient errors.

### 100 конкурентных запросов

Использовать детерминированный seed synthetic wallets и запросов, отдельные транзакции/соединения и реальные PostgreSQL locks. Собрать успехи и бизнес-отклонения; каждый успешный перевод учитывается ровно один раз, общий P2P balance постоянен, отрицательных остатков нет. Фиксировать seed, версии, concurrency, timeout и длительность.

## Отчёт

Для каждой демонстрации сохранять команду запуска, commit, окружение, fixtures/seed, expected/actual result и reconciliation summary. Сейчас исполняемые сценарии и результаты ещё не подготовлены. Полный набор acceptance cases: [test-plan.md](test-plan.md).

# CreateTransferUseCase

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

Application-обработчик перевода между разными кошельками в одной валюте.
`CreateTransferCommand.user_id` задаётся доверенным вызывающим кодом из JWT;
`idempotency_key` обязателен и передаётся из заголовка Idempotency-Key.
Результат — `CreateTransferResult(transfer_id=...)`, по стилю CreateWalletResult.

Проверки: UUID, положительная целая сумма в пределах signed BIGINT, валюта,
разные кошельки, корректный ключ, существование и активность actor, владение
исходным wallet, ACTIVE обоих wallets, валюты обоих wallets и accounts,
наличие связанных balances/LIABILITY accounts, активность accounts,
достаточность средств, overflow баланса и версии проекции.

`max_amount_minor` задаёт дополнительный бизнес-лимит. По умолчанию действует
технический предел signed BIGINT; отдельный продуктовый лимит ещё нужно выбрать
и задать через TRANSFER_MAX_AMOUNT_MINOR. Проверка активности владельца
получателя отдельно пока не добавлена. FROZEN/CLOSED wallets не принимают и
не отправляют переводы.

Порядок работы:

1. Валидация команды и чтение активного actor.
2. Атомарный claim `(user_id, transfer.create, idempotency_key)`.
3. При replay: сравнить canonical payload hash и вернуть прежний transfer_id.
   При несовпадении — IdempotencyConflictError; незавершённый claim —
   IdempotencyInProgressError. Текущий бизнес-лимит не отменяет старый результат.
4. Заблокировать и повторно проверить actor, затем оба wallets по UUID,
   оба balances по wallet UUID и оба accounts по wallet UUID.
5. После locks получить один now, создать Transfer, изменить проверенные копии
   balances, вызвать complete и построить LedgerTransaction.for_transfer.
   Фабрика сама создаёт две LedgerEntry; повторно создавать их не нужно.
6. Сохранить Transfer, весь journal, обе проекции и результат claim.
7. Один commit. Результат возвращается после выхода из UoW.

Ключи сравниваются в scope пользователя и операции; hash содержит только
sender/receiver wallet IDs, amount_minor и currency. При повторе с новым ключом
создаётся новое намерение перевода. Текущий replay хранит полный результат
handler — один transfer_id. Если результат расширится, нужно расширить snapshot.

Бизнес-ошибки и технические исключения выходят через UoW и откатывают попытку,
включая новый claim. REJECTED сейчас не сохраняется; для сохранения отказов
нужна отдельно согласованная ветка commit без journal и изменений балансов.
Автоматического повтора транзакции внутри handler нет.

### Граница готовности

Реализованы handler, SQL repositories, UoW и POST /v1/transfers.
Миграция 20261112_04 создаёт финансовые таблицы и ограничения PostgreSQL.
HTTP требует Bearer JWT и Idempotency-Key; результат — transfer_id (201).
Presentation dependency дополнительно ограничивает POST-запросы через Redis:
по умолчанию 30/минуту на пользователя и 100/минуту на IP; настройки
TRANSFER_RATE_LIMIT_USER_PER_MINUTE и TRANSFER_RATE_LIMIT_IP_PER_MINUTE.
HTTP retries, включая replay, также учитываются. При превышении — 429 с Retry-After,
при недоступном Redis — 503 без вызова handler. JWT и обязательный ключ проверяются
до расходования бюджета. Денежные проверки и идемпотентность остаются в handler/UoW.

Idempotency adapter обязан атомарно сериализовать конкурирующие claims,
удерживать их в той же SQL-транзакции, использовать ограниченное ожидание,
не сохранять незавершённый claim отдельным commit и хранить результат минимум
24 часа. Maintenance по умолчанию архивирует полные записи после семи дней
в постоянные квитанции replay: поздние повторы остаются безопасными.
См. [обслуживание](../../../../../docs/maintenance.md).

Все repositories обязаны использовать ту же транзакцию, без своих commits.
PostgreSQL должен обеспечивать ограничения связей и валют, уникальный journal
для операции, балансировку и защиту проведённых записей от изменений.
Unit-тесты проверяют контракт handler и передачу ошибок в UoW. PostgreSQL-тесты
проверяют конкуренцию, повтор ключа, ограниченное ожидание, rollback и ограничения
journal. Служебная reconciliation query и CLI реализованы отдельно;
разграничение привилегий DB roles остаётся эксплуатационной задачей.

### Чтение переводов

`GetTransferQuery.execute(GetTransferCommand(user_id, transfer_id))` возвращает
один TransferDTO. Actor должен существовать и быть ACTIVE. Reader обязан
применять SQL-предикат участника: sender owner OR receiver owner = actor.
Для отсутствующего и чужого перевода reader возвращает None, query выдаёт
одинаковый TransferNotFoundError. В DTO нет email, IP, private owner IDs или
чужих балансов. Замороженные/закрытые wallets сохраняют доступную историю.

`GetMyTransfersQuery.execute(GetMyTransfersCommand(...))` возвращает
`PageDTO[TransferDTO](items, next_cursor)`. Фильтры: свой wallet_id, currency,
status, direction, created_from, created_to. Диапазон дат — [from, to), даты
обязательно timezone-aware. Лимит по умолчанию 20, допустим 1..100.

Direction относительно пользователя: INCOMING, OUTGOING или INTERNAL при двух
своих wallets. Эта семантика сохраняется и с wallet_id filter. Это список
бизнес-переводов; REJECTED отображается только если такая операция сохранена.
Текущий CreateTransferUseCase откатывает отказы и их не сохраняет.

Reader должен:

- Всегда ограничивать результат actor в SQL; filters только сужают scope.
- При wallet filter проверять, что выбранный wallet принадлежит actor;
  чужой/отсутствующий wallet даёт пустой список. Фильтр не предназначен для
  поиска по кошельку контрагента.
- Возвращать не более requested limit строк по (created_at DESC, id DESC).
- Применять keyset-предикат (created_at, id) < cursor position.
- Исключать дубли внутренних переводов до LIMIT; делать проекцию без N+1.

Query запрашивает limit+1, возвращает первые limit и строит cursor по последней
возвращённой записи, если есть lookahead. Последняя/пустая страница имеет
next_cursor=None. Нет FOR UPDATE, изменений сущностей или commit.

Общий ICursorCodec имеет реализацию HMACCursorCodec (HMAC-SHA256). Нужен
серверный секретный bytes-key минимум 32 байта, общий для экземпляров API;
ключ скрыт из repr. DI использует PAGINATION_SECRET_KEY либо отдельный HMAC-ключ,
выведенный из JWT_SECRET_KEY с контекстом fincore-pagination-v1.
Cursor подписан и привязан к actor, имени query и всем нормализованным фильтрам;
эквивалентные представления дат в разных timezone дают одинаковый context. Размер страницы
можно менять. Повреждённый cursor, другая подпись/actor/filters дают
InvalidCursorError. Cursor не является разрешением на чтение и не обещает
единый snapshot между страницами. Ротация ключа инвалидирует старые cursors.

Queries подключены через SQL TransferReader к GET /v1/transfers и
GET /v1/transfers/{transfer_id}. Доступ участников, keyset pagination и
дедупликация проверяются с PostgreSQL. amount_minor в HTTP сериализуется
десятичной строкой для точности JavaScript.

<a id="en"></a>

## English

Application handler for transfers between distinct wallets in the same currency.
`CreateTransferCommand.user_id` is supplied by trusted calling code from the JWT;
`idempotency_key` is required and comes from the Idempotency-Key header.
The result is `CreateTransferResult(transfer_id=...)`, following CreateWalletResult.

Checks cover UUIDs, a positive integer amount within signed BIGINT, currency,
distinct wallets, a valid key, an existing active actor, ownership of the sender
wallet, ACTIVE status of both wallets, matching wallet/account currencies,
associated balances/LIABILITY accounts, active accounts, sufficient funds,
and balance/projection-version overflow.

`max_amount_minor` adds a business limit. The default is the technical signed
BIGINT limit; a separate product limit still needs to be chosen and configured
through TRANSFER_MAX_AMOUNT_MINOR. The recipient owner's active status is not
separately checked yet. FROZEN/CLOSED wallets cannot send or receive transfers.

Execution order:

1. Validate the command and read the active actor.
2. Atomically claim `(user_id, transfer.create, idempotency_key)`.
3. On replay, compare the canonical payload hash and return the original transfer_id.
   A mismatch raises IdempotencyConflictError; an unfinished claim raises
   IdempotencyInProgressError. Current business limits do not invalidate an old result.
4. Lock and recheck the actor, then both wallets ordered by UUID, both balances
   ordered by wallet UUID, and both accounts ordered by wallet UUID.
5. After locking, obtain one now, create Transfer, modify validated balance copies,
   call complete and build LedgerTransaction.for_transfer. The factory creates
   both LedgerEntry objects; do not create them again.
6. Save Transfer, the entire journal, both projections and the claim result.
7. Commit once. Return the result after leaving the UoW.

Keys are compared within user/operation scope; the hash includes only sender and
receiver wallet IDs, amount_minor and currency. A new key represents a new transfer
intent. Replay currently stores the entire handler result: one transfer_id.
Expand the snapshot if the handler result expands.

Business errors and infrastructure exceptions propagate through the UoW, rolling
back the attempt, including a new claim. REJECTED is not currently persisted;
persisting refusals requires a separately agreed commit path without a journal
or balance changes. The handler does not automatically retry transactions.

### Implementation status

The handler, SQL repositories, UoW and POST /v1/transfers are implemented.
Migration 20261112_04 creates financial tables and PostgreSQL constraints.
HTTP requires Bearer JWT and Idempotency-Key; the result is transfer_id (201).
A presentation dependency also limits POST requests through Redis: defaults are
30/user/minute and 100/IP/minute, configured by TRANSFER_RATE_LIMIT_USER_PER_MINUTE
and TRANSFER_RATE_LIMIT_IP_PER_MINUTE. HTTP retries, including replays, count.
Exhaustion returns 429 with Retry-After; unavailable Redis returns 503 without
calling the handler. JWT and the required key are checked before consuming the
budget. Monetary checks and idempotency remain in the handler/UoW.

The idempotency adapter must atomically serialize competing claims in the same SQL
transaction, use bounded waiting, never commit an unfinished claim separately,
and retain the result for at least 24 hours. Maintenance defaults to archiving full
records after seven days into permanent replay receipts; late retries remain safe.
See [maintenance](../../../../../docs/maintenance.md).

All repositories use the same transaction and do not commit independently.
PostgreSQL enforces relationship/currency constraints, a unique journal per
operation, balancing and immutability of posted records. Unit tests check the
handler contract and error propagation into the UoW. PostgreSQL tests cover
concurrency, key replay, bounded waiting, rollback and journal constraints.
The operational reconciliation query and CLI are implemented separately;
database role privileges remain an operational task.

### Reading transfers

`GetTransferQuery.execute(GetTransferCommand(user_id, transfer_id))` returns one
TransferDTO. The actor must exist and be ACTIVE. The reader must apply a SQL
participant predicate: sender owner OR receiver owner = actor. For missing and
foreign transfers, the reader returns None and the query raises the same
TransferNotFoundError. The DTO excludes email, IP, private owner IDs and other
users' balances. Frozen/closed wallets retain readable history.

`GetMyTransfersQuery.execute(GetMyTransfersCommand(...))` returns
`PageDTO[TransferDTO](items, next_cursor)`. Filters: an owned wallet_id, currency,
status, direction, created_from and created_to. Dates must be timezone-aware;
the interval is [from, to). Default limit is 20, allowed range 1..100.

Direction is relative to the user: INCOMING, OUTGOING or INTERNAL for two owned
wallets. This also applies with a wallet_id filter. These are business transfers;
REJECTED appears only if such an operation is persisted. CreateTransferUseCase
currently rolls back refusals rather than storing them.

The reader must:

- Always restrict results to the actor in SQL; filters only narrow this scope.
- Check ownership of a wallet filter; a missing/foreign wallet returns an empty
  list. The filter does not search by a counterparty's wallet.
- Return no more than the requested limit, ordered by (created_at DESC, id DESC).
- Apply the keyset predicate (created_at, id) < cursor position.
- Deduplicate internal transfers before LIMIT and project without N+1 queries.

The query requests limit+1, returns the first limit items and builds a cursor from
the last returned item when lookahead exists. Empty/final pages have
next_cursor=None. There is no FOR UPDATE, entity mutation or commit.

The shared ICursorCodec is implemented by HMACCursorCodec (HMAC-SHA256). It needs
a server-side secret bytes key of at least 32 bytes, shared by API instances and
hidden from repr. DI uses PAGINATION_SECRET_KEY or a separate HMAC key derived
from JWT_SECRET_KEY with the fincore-pagination-v1 context. Cursors are signed
and bound to the actor, query name and all normalized filters. Equivalent dates
in different timezones yield the same context. Page size may change. Corruption,
a different signature/actor/filters raises InvalidCursorError. A cursor is not
read authorization and does not guarantee a single snapshot across pages.
Key rotation invalidates old cursors.

Queries are connected through SQL TransferReader to GET /v1/transfers and
GET /v1/transfers/{transfer_id}. PostgreSQL tests cover participant access,
keyset pagination and deduplication. HTTP serializes amount_minor as a decimal
string to preserve JavaScript precision.

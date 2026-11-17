# CreateTransferUseCase

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

## Граница готовности

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
24 часа. После очистки replay безопасный слепой повтор не гарантируется.

Все repositories обязаны использовать ту же транзакцию, без своих commits.
PostgreSQL должен обеспечивать ограничения связей и валют, уникальный journal
для операции, балансировку и защиту проведённых записей от изменений.
Unit-тесты проверяют контракт handler и передачу ошибок в UoW. PostgreSQL-тесты
проверяют конкуренцию, повтор ключа, ограниченное ожидание, rollback и ограничения
journal. Служебная reconciliation query и отдельные привилегии DB roles остаются
самостоятельной работой.

## Чтение переводов

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

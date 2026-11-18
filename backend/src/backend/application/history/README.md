# История проведённых движений / Posted transaction history

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

Подготовлены `GetMyTransactionsQuery` в этом модуле и
`GetWalletTransactionsQuery` в `application/wallet/queries`.
Обе возвращают `PageDTO(items, next_cursor)`, проверяют активного actor и работают
через `uow.transaction_history_reader`. Нет FOR UPDATE, изменений или commit.

История строится по проведённым LedgerTransaction/Entry с projection исходной
Transfer/SandboxTopUp. Это фактические движения: REJECTED и PENDING сюда не входят.
`TransactionDTO.id` — ID journal, source_id — ID бизнес-операции, source_type —
LedgerTransactionKindEnum (p2p_transfer/sandbox_topup). Для top-up sender_wallet_id
равен None, receiver_wallet_id — целевой wallet. Суммы положительные; знак задаётся
direction. Нет чужих балансов, email, IP или идентификатора оператора.

### Доступ и направление

- Общая история: sender OR receiver wallet принадлежит actor, предикат в SQL.
  Перевод между своими wallets — одна строка INTERNAL, дедупликация до LIMIT.
- История конкретного wallet: обязательный owner scope; чужой/отсутствующий wallet
  даёт None от reader и WalletNotFoundError из query. Свой без движений даёт [].
- Все статусы wallet остаются читаемыми, включая FROZEN/CLOSED.
- Общая история с wallet_id filter сначала проверяет его ownership; чужой или
  отсутствующий wallet даёт пустой список. Направление относительно выбранного
  wallet — INCOMING/OUTGOING, в том числе для перевода между своими wallets.
- WalletTransactionDTO добавляет wallet_id и свойство counterparty_wallet_id;
  при top-up контрагент отсутствует. Для одного wallet направление INTERNAL
  недопустимо. Также нельзя совмещать wallet filter и INTERNAL в общей истории.

### Фильтры и пагинация

Фильтры: kind, currency, direction, posted_from, posted_to; у общей истории
дополнительно wallet_id. Даты timezone-aware, диапазон [from, to), from < to.
Они только сужают обязательный owner scope и не содержат произвольного user_id.

Default limit=20, допустим 1..100. Reader запрашивается с limit+1, сортировка
(posted_at DESC, journal ID DESC), keyset-предикат tuple < cursor position.
Следующий cursor строится по последней выданной записи, не по lookahead.
Пустая/последняя страница возвращается с next_cursor=None.

Используется общий ICursorCodec/HMACCursorCodec. Context подписанного cursor
содержит query name, actor, выбранный wallet и все нормализованные фильтры.
Cursor другой query, пользователя, кошелька или фильтров недействителен;
эквивалентные даты с разными timezone допускаются. Page size можно менять.
Cursor не даёт полномочий и не фиксирует snapshot между HTTP-страницами.

### Готовность

Queries подключены через SQL TransactionHistoryReader и UoW к
GET /v1/users/me/transactions и GET /v1/wallets/{wallet_id}/transactions.
SQL ownership, фильтры, чтение закрытых wallets, дедупликация и keyset pagination
проверяются интеграционными тестами PostgreSQL. DI использует PAGINATION_SECRET_KEY
либо отдельный ключ, выведенный из JWT_SECRET_KEY. amount_minor в HTTP — десятичная
строка, остальные правила DTO сохраняются.

<a id="en"></a>

## English

`GetMyTransactionsQuery` lives in this module;
`GetWalletTransactionsQuery` lives in `application/wallet/queries`.
Both return `PageDTO(items, next_cursor)`, validate an active actor and use
`uow.transaction_history_reader`. There is no FOR UPDATE, mutation or commit.

History uses posted LedgerTransaction/Entry records with a projection of the
source Transfer/SandboxTopUp. These are actual movements: REJECTED and PENDING
are excluded. `TransactionDTO.id` is the journal ID; source_id is the business
operation ID; source_type is LedgerTransactionKindEnum (p2p_transfer/sandbox_topup).
For top-ups, sender_wallet_id is None and receiver_wallet_id is the target wallet.
Amounts are positive; direction determines the sign. Other users' balances,
email, IP and operator identity are excluded.

### Access and direction

- Overall history: sender OR receiver wallet belongs to the actor, enforced in SQL.
  A transfer between owned wallets is one INTERNAL row, deduplicated before LIMIT.
- Wallet-specific history: mandatory owner scope; a missing/foreign wallet returns
  None from the reader and WalletNotFoundError from the query. An owned wallet
  without movements returns [].
- All wallet statuses remain readable, including FROZEN/CLOSED.
- Overall history with a wallet_id filter first checks its ownership; a missing
  or foreign wallet returns an empty list. Direction is relative to that wallet:
  INCOMING/OUTGOING, including transfers between owned wallets.
- WalletTransactionDTO adds wallet_id and counterparty_wallet_id; a top-up has no
  counterparty. INTERNAL is invalid for a single wallet. An overall-history
  wallet filter also cannot be combined with INTERNAL.

### Filters and pagination

Filters: kind, currency, direction, posted_from and posted_to; overall history
also supports wallet_id. Dates must be timezone-aware, interval [from, to),
from < to. Filters only narrow mandatory owner scope and accept no arbitrary user_id.

Default limit=20, allowed range 1..100. The reader is requested with limit+1,
ordered by (posted_at DESC, journal ID DESC), with keyset tuple < cursor position.
The next cursor comes from the last returned item, not the lookahead item.
Empty/final pages return next_cursor=None.

The shared ICursorCodec/HMACCursorCodec is used. Signed cursor context includes
the query name, actor, selected wallet and all normalized filters. A cursor for
another query, user, wallet or filter set is invalid; equivalent dates in different
timezones are accepted. Page size may change. Cursors grant no authorization
and do not fix a snapshot across HTTP pages.

### Implementation status

Queries connect through SQL TransactionHistoryReader and UoW to
GET /v1/users/me/transactions and GET /v1/wallets/{wallet_id}/transactions.
PostgreSQL integration tests cover SQL ownership, filters, closed wallets,
deduplication and keyset pagination. DI uses PAGINATION_SECRET_KEY or a separate
key derived from JWT_SECRET_KEY. HTTP amount_minor is a decimal string;
other DTO rules remain unchanged.

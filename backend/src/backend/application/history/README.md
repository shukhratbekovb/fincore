# Queries истории проведённых движений

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

## Доступ и направление

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

## Фильтры и пагинация

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

## Готовность

Queries подключены через SQL TransactionHistoryReader и UoW к
GET /v1/users/me/transactions и GET /v1/wallets/{wallet_id}/transactions.
SQL ownership, фильтры, чтение закрытых wallets, дедупликация и keyset pagination
проверяются интеграционными тестами PostgreSQL. DI использует PAGINATION_SECRET_KEY
либо отдельный ключ, выведенный из JWT_SECRET_KEY. amount_minor в HTTP — десятичная
строка, остальные правила DTO сохраняются.

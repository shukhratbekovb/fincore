# Чтение балансов / Reading balances

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

`GetWalletBalanceQuery` и `GetMyBalanceSummaryQuery` находятся в
`application/wallet/queries`. DTO и IWalletBalanceReader — в этом модуле.
Обе query проверяют активного actor, не берут FOR UPDATE и не выполняют commit.
Существующий GetWalletQuery с balance_minor продолжает работать без изменений.

### Баланс кошелька

`GetWalletBalanceCommand(user_id, wallet_id)` возвращает WalletBalanceDTO:
wallet_id, currency, posted_minor, available_minor, spendable_minor, version,
updated_at и as_of. Обязательный owner scope reader применяет в SQL.
Чужой/отсутствующий wallet -> None -> WalletNotFoundError. Свой wallet без
обязательного balance/account -> WalletAccountingStateError, а не ноль/404.
updated_at относится к проекции WalletBalance, не к metadata Wallet.

### Сводка

`GetMyBalanceSummaryCommand(user_id, currency=None)` возвращает BalanceSummaryDTO
с totals по валютам и общим as_of. Суммы всех подходящих wallets рассчитываются
reader в одном согласованном snapshot, независимо от пагинации списка wallets.
Валюта — необязательный фильтр, статусы не являются произвольным клиентским scope.

Политика текущего контракта:

- posted включает ACTIVE, FROZEN и CLOSED wallets.
- available равен posted, пока нет holds; это не проверка права на перевод.
- spendable учитывает available только ACTIVE wallets, у FROZEN/CLOSED равен 0.
- USD и UZS представлены отдельными totals, общей суммы разных валют нет.
- Нет подходящих wallets -> totals=[]; wallet с реальным 0 даёт нулевой total.
- Отсутствующие/несогласованные balance и LIABILITY account — ошибка целостности.
  Чтение допускает закрытые счета закрытых wallets; ensure_active здесь не нужен.

DTO проверяют неотрицательные int без bool/float, spendable <= available <= posted,
timezone-aware даты и уникальность валют в summary. Один wallet и его version
должны помещаться в signed BIGINT. Сводная сумма нескольких wallets может быть
больше BIGINT и сохраняется как Python int без усечения. HTTP сериализует суммы
и version десятичными строками для точности JavaScript.

as_of — метка чтения БД, не версия ledger и не обещание общего snapshot с другим
запросом. Reader должен получать баланс и его timestamp в одном SQL snapshot;
для нескольких запросов внутри reader нужна соответствующая snapshot isolation.

### Готовность

Queries подключены через SQL WalletBalanceReader и UoW к
GET /v1/wallets/{wallet_id}/balance и GET /v1/users/me/balances.
Reader проверяет ownership до раскрытия ошибок чужой проекции, целостность
связей/валют через LEFT JOIN. Summary получает суммы и as_of одним SQL statement.
Интеграционные тесты PostgreSQL проверяют ACL, пустые и нулевые остатки,
повреждённую проекцию, статусы и суммы больше BIGINT.

<a id="en"></a>

## English

`GetWalletBalanceQuery` and `GetMyBalanceSummaryQuery` live in
`application/wallet/queries`. DTOs and IWalletBalanceReader live in this module.
Both queries check an active actor, take no FOR UPDATE locks and do not commit.
The existing GetWalletQuery with balance_minor continues to work unchanged.

### Wallet balance

`GetWalletBalanceCommand(user_id, wallet_id)` returns WalletBalanceDTO:
wallet_id, currency, posted_minor, available_minor, spendable_minor, version,
updated_at and as_of. The reader applies mandatory owner scope in SQL.
A foreign/missing wallet → None → WalletNotFoundError. An owned wallet missing
its required balance/account raises WalletAccountingStateError rather than
returning zero/404. updated_at belongs to the WalletBalance projection, not Wallet metadata.

### Summary

`GetMyBalanceSummaryCommand(user_id, currency=None)` returns BalanceSummaryDTO
with per-currency totals and one as_of timestamp. The reader calculates totals
across all eligible wallets in one consistent snapshot, independently of wallet
list pagination. Currency is an optional filter; statuses are not arbitrary
client-controlled scope.

Current contract policy:

- posted includes ACTIVE, FROZEN and CLOSED wallets.
- available equals posted until holds exist; it does not authorize a transfer.
- spendable includes available only for ACTIVE wallets and is 0 for FROZEN/CLOSED.
- USD and UZS have separate totals; different currencies are never combined.
- No matching wallets → totals=[]; a wallet with an actual zero yields a zero total.
- Missing/inconsistent balances and LIABILITY accounts are integrity errors.
  Reads allow closed accounts belonging to closed wallets; ensure_active is not needed here.

DTOs validate nonnegative int values excluding bool/float, spendable <= available
<= posted, timezone-aware dates and unique summary currencies. A single wallet's
balance and version must fit signed BIGINT. Totals across several wallets may
exceed BIGINT and remain Python int without truncation. HTTP serializes amounts
and version as decimal strings to preserve JavaScript precision.

as_of marks the database read; it is not a ledger version or a promise of a shared
snapshot with another request. The reader must obtain the balance and timestamp
in one SQL snapshot; multiple reader statements need appropriate snapshot isolation.

### Implementation status

Queries connect through SQL WalletBalanceReader and UoW to
GET /v1/wallets/{wallet_id}/balance and GET /v1/users/me/balances.
The reader checks ownership before exposing projection errors and uses LEFT JOIN
to validate relationships/currencies. Summary gets amounts and as_of in one SQL
statement. PostgreSQL integration tests cover ACL, empty and zero balances,
corrupted projections, statuses and totals exceeding BIGINT.

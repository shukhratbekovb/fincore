# Чтение балансов

`GetWalletBalanceQuery` и `GetMyBalanceSummaryQuery` находятся в
`application/wallet/queries`. DTO и IWalletBalanceReader — в этом модуле.
Обе query проверяют активного actor, не берут FOR UPDATE и не выполняют commit.
Существующий GetWalletQuery с balance_minor продолжает работать без изменений.

## Баланс кошелька

`GetWalletBalanceCommand(user_id, wallet_id)` возвращает WalletBalanceDTO:
wallet_id, currency, posted_minor, available_minor, spendable_minor, version,
updated_at и as_of. Обязательный owner scope reader применяет в SQL.
Чужой/отсутствующий wallet -> None -> WalletNotFoundError. Свой wallet без
обязательного balance/account -> WalletAccountingStateError, а не ноль/404.
updated_at относится к проекции WalletBalance, не к metadata Wallet.

## Сводка

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

## Готовность

Queries подключены через SQL WalletBalanceReader и UoW к
GET /v1/wallets/{wallet_id}/balance и GET /v1/users/me/balances.
Reader проверяет ownership до раскрытия ошибок чужой проекции, целостность
связей/валют через LEFT JOIN. Summary получает суммы и as_of одним SQL statement.
Интеграционные тесты PostgreSQL проверяют ACL, пустые и нулевые остатки,
повреждённую проекцию, статусы и суммы больше BIGINT.

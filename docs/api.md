# REST API v1

Срез реализации: **15 ноября 2026**. Фактический base path FastAPI — **`/v1`**. [PRD](../FinCore_PRD_MVP_v1.0%20%281%29.pdf) и ранние примеры `/api/v1` описывают исторический baseline.

Полные схемы, примеры и описания генерируются из приложения:

- ReDoc: `/redoc/ru`, `/redoc/en`; `/redoc` перенаправляет на русский вариант.
- OpenAPI: `/openapi/ru.json`, `/openapi/en.json`; `/openapi.json` — английская схема.
- Swagger UI: `/docs`.

При локальном API на порту 8000: [ReDoc RU](http://127.0.0.1:8000/redoc/ru), [ReDoc EN](http://127.0.0.1:8000/redoc/en). В production API не публикуется напрямую; доступ к документации требует отдельной настройки владельцем VPS.

## Общий контракт

JSON; даты ISO 8601 с timezone. Идентификаторы — UUID. Валюты: `USD`, `EUR`, `JPY`, `CHF`, `GBP`, `UZS`, `CAD`, `RUB`; обмен валют не выполняется. Суммы передаются в minor units выбранной валюты без float. Денежный вход допускает положительный integer либо десятичную строку, верхняя граница — `2**63 - 1`; денежные ответы и версия balance сериализуются строками для точности в JavaScript.

Защищённый FastAPI endpoint принимает `Authorization: Bearer <access_token>`. В браузере используется Next.js gateway `/api/backend/*`, который хранит access/refresh в HttpOnly cookies и добавляет Bearer на сервере. Поэтому прямой token-pair ответ API и ответ браузерного gateway различаются: gateway возвращает `{ "authenticated": true }` после login/refresh, сохраняя секреты в cookies.

`X-Request-ID` возвращается API как correlation header. Auth/финансовые ответы не должны кэшироваться. Login/refresh получают IP из доверенного ASGI client context, user-agent — из заголовка. Production proxy-контракт описан в [архитектуре](architecture.md) и [deployment](deployment.md).

## Авторизация

Пути в таблицах указаны **после `/v1`**.

| Метод | Путь                           | Успех            | Вход и поведение                                                                                                      |
| ----- | ------------------------------ | ---------------- | --------------------------------------------------------------------------------------------------------------------- |
| POST  | `/auth/register`               | 201 `{user_id}`  | `username`, `email`; pending user и письмо подтверждения                                                              |
| POST  | `/auth/confirm`                | 204              | `token`, `password`; установка пароля и активация                                                                     |
| POST  | `/auth/confirm/resend`         | 202 `{message}`  | `email`; одинаковый ответ для неизвестного, активного и pending аккаунта; прежние регистрационные ссылки аннулируются |
| POST  | `/auth/login`                  | 200 token pair   | `username`, `password`; новая сессия                                                                                  |
| POST  | `/auth/refresh`                | 200 token pair   | `refresh_token`; ротация, reuse отзывает сессию                                                                       |
| POST  | `/auth/logout`                 | 204              | `refresh_token`; отзыв соответствующей сессии                                                                         |
| POST  | `/auth/change-password`        | 204              | Bearer; `current_password`, `new_password`; отзыв сессий                                                              |
| POST  | `/auth/password-reset/request` | 202 `{message}`  | `email`; одинаковый ответ независимо от подходящего аккаунта                                                          |
| POST  | `/auth/password-reset/confirm` | 200 `{password}` | `token`; новый сгенерированный пароль возвращается один раз, сессии отзываются                                        |

Токены подтверждений передаются в JSON body. Письмо восстановления содержит ссылку подтверждения; новый пароль создаётся только после её использования и не отправляется в письме. Точная password policy и ошибки доступны в OpenAPI и domain validation.

## Пользователь и сессии

| Метод  | Путь                              | Успех       | Поведение                                            |
| ------ | --------------------------------- | ----------- | ---------------------------------------------------- |
| GET    | `/users/me`                       | 200 profile | ID, username, email, дата создания                   |
| GET    | `/users/me/sessions`              | 200 array   | Активные собственные сессии с IP и user-agent        |
| DELETE | `/users/me/sessions`              | 204         | Отзыв всех собственных сессий                        |
| DELETE | `/users/me/sessions/{session_id}` | 204         | Отзыв одной собственной сессии                       |
| GET    | `/users/me/balances`              | 200 summary | Суммы отдельно по валютам, необязательный `currency` |
| GET    | `/users/me/transactions`          | 200 page    | Единая история проведённых операций                  |

## Кошельки, получатель и переводы

| Метод | Путь                                | Успех               | Поведение                                                                                                     |
| ----- | ----------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------- |
| POST  | `/wallets`                          | 201 `{wallet_id}`   | `name`, `currency` (по умолчанию USD); создаёт balance и liability account                                    |
| GET   | `/wallets`                          | 200 array           | Свои кошельки с балансами; `currency`, `status`, `sort_by`                                                    |
| GET   | `/wallets/{wallet_id}`              | 200 wallet          | Только владелец                                                                                               |
| PATCH | `/wallets/{wallet_id}`              | 204                 | `name`; переименование                                                                                        |
| POST  | `/wallets/{wallet_id}/close`        | 204                 | Закрытие при нулевом балансе                                                                                  |
| POST  | `/wallets/{wallet_id}/freeze`       | 204                 | Заморозка собственного кошелька                                                                               |
| POST  | `/wallets/{wallet_id}/unfreeze`     | 204                 | Разморозка собственного кошелька                                                                              |
| GET   | `/wallets/{wallet_id}/balance`      | 200 balance         | `posted_minor`, `available_minor`, `spendable_minor`, version, timestamps                                     |
| GET   | `/wallets/{wallet_id}/transactions` | 200 page            | Проведённая история одного кошелька                                                                           |
| POST  | `/transfer-recipients/resolve`      | 200 recipient       | Точный номер; только активный кошелёк активного получателя                                                    |
| POST  | `/transfers`                        | 201 `{transfer_id}` | Bearer и `Idempotency-Key`; перевод между кошельками одной валюты                                             |
| GET   | `/transfers`                        | 200 page            | Только свои переводы как отправителя/получателя                                                               |
| GET   | `/transfers/{transfer_id}`          | 200 transfer        | Только участники                                                                                              |
| POST  | `/sandbox/top-ups`                  | 201 `{top_up_id}`   | `wallet_id`, `amount_minor`, `currency`; Bearer, `Idempotency-Key`, разрешение оператора и включённый sandbox |

Resolve принимает строку ровно из 20 ASCII-цифр, сохраняя ведущие нули:

```json
{ "wallet_number": "00001234567890123456" }
```

Ответ:

```json
{
  "wallet_id": "f7f1a726-8d5a-45d2-a2c5-fdaa348e9b23",
  "number": "00001234567890123456",
  "currency": "CAD",
  "owner": "recipient_username"
}
```

`owner` — username владельца найденного кошелька. Неизвестный номер, frozen/closed кошелёк и неактивный владелец дают одинаковый `404 wallet_not_found`. Результат resolve не резервирует получателя: при переводе статусы проверяются повторно под блокировкой.

После resolve frontend использует возвращённый UUID в команде:

```http
POST /v1/transfers
Authorization: Bearer <access_token>
Idempotency-Key: <one-key-for-this-intent>
Content-Type: application/json
```

```json
{
  "sender_wallet_id": "<sender-uuid>",
  "receiver_wallet_id": "<resolved-recipient-uuid>",
  "amount_minor": "10000",
  "currency": "CAD"
}
```

Одинаковый ключ, пользователь, scope и payload возвращают прежний ID без повторного списания. Изменённый payload — `409 idempotency_conflict`; занятая резервация — `409 idempotency_in_progress`, повторяется с прежними ключом и payload. После очистки полного кеша сохраняется постоянный компактный receipt. Сетевой timeout не означает rollback: смена ключа при неизвестном результате может создать вторую операцию.

Создание кошелька не требует `Idempotency-Key`. Название/номер кошелька не заменяют UUID в финансовой команде. API сохраняет UUID в ответах, даже когда UI скрывает их из реквизитов.

## Балансы, фильтры и пагинация

`available_minor = posted_minor` в текущем MVP. `spendable_minor` равен балансу активного кошелька и нулю для frozen/closed. Summary не складывает разные валюты в одно число. Авторитетный баланс не рассчитывается клиентом из загруженной страницы истории.

Страницы содержат `{items, next_cursor}`; `limit` по умолчанию 20, допустимо 1–100. Cursor подписан, связан с пользователем/контекстом и фильтрами; при переходе страницы параметры нужно сохранять. История сортируется по `posted_at` и ID, переводы — по `created_at` и ID, от новых к старым. История содержит `source_type`/`source_id` и journal `id`; перевод между своими кошельками представлен в общей истории с учётом его направления.

Фильтры переводов: `wallet_id`, `currency`, `status`, `direction`, `created_from`, `created_to`. Фильтры истории: `kind`, `currency`, `direction`, `posted_from`, `posted_to`; общая история также принимает `wallet_id`. Допустимые enum и границы дат описаны в RU/EN OpenAPI.

## Ошибки, лимиты и health

Известные ошибки и ошибки валидации возвращают единый envelope:

```json
{
  "detail": {
    "code": "insufficient_funds",
    "message": "Insufficient available funds",
    "errors": []
  }
}
```

Основные статусы: 400 — непригодный confirmation/reset token; 401 — credentials/access/refresh; 403 — неактивный пользователь или нет sandbox-разрешения; 404 — ресурс отсутствует либо скрыт ACL; 409 — конфликт ключа/состояния; 422 — формат, валюта, сумма, недостаток средств, фильтр или cursor. Неожиданный 500 не обязан соответствовать этому envelope; SQL и traceback клиенту не раскрываются.

Redis limiter подключён к login, регистрации, resend, password reset, resolve и переводу. Превышение — `429` с `Retry-After` (секунды); недоступность limiter — `503 rate_limiter_unavailable`. Лимиты запросов и максимальная сумма одной операции настраиваются отдельно.

`GET /health` и `/health/live` непрефиксные, возвращают 200 при работе процесса. `/health/ready` возвращает 200 либо 503 по PostgreSQL/Redis. Next.js `/health` проверяет frontend. Служебные reconciliation и cleanup запускаются CLI, публичных HTTP endpoints для них нет.

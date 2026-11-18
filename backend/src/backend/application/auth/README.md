# Сброс пароля: application-контракт / Password reset: application contract

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

`RequestPasswordResetUseCase.execute(RequestPasswordResetCommand)` возвращает None
как для неизвестного аккаунта, так и для подходящего под условия сброса.
Только активный аккаунт с установленным паролем получает challenge PASSWORD_RESET
и сообщение SendPasswordResetConfirmation. Пароль, сессии и предыдущие ссылки
не меняются до подтверждения сброса. Генерация/хеширование токена выполняются
и для неизвестного аккаунта; это не гарантирует одинаковое время HTTP-ответа.

`ConfirmPasswordResetUseCase.execute(ConfirmPasswordResetCommand)` однократно
возвращает ConfirmPasswordResetResult.password после commit и успешного выхода
из UoW. Вход содержит только токен сброса. Сгенерированный RawPassword хешируется
через IPasswordHasher; в User сохраняется только хеш. Транзакция использует
challenge, отзывает сессии, инвалидирует остальные неиспользованные challenges
PASSWORD_RESET пользователя и добавляет SendPasswordChangedNotification без пароля.
Отсутствующий, истёкший, использованный, неподходящий по назначению или условиям
токен даёт одинаковый InvalidPasswordResetTokenError. Инфраструктурные ошибки
передаются вызывающему коду обычным образом.

Сброс читает идентификаторы challenge без блокировки, блокирует пользователя,
затем заново читает challenge через FOR UPDATE. Все пути создания/подтверждения
сброса сериализуются блокировкой пользователя. Подтверждение регистрации
отклоняет challenge назначения reset до блокировки пользователя, исключая
обратный порядок блокировок. Адаптеры репозитория должны сохранять неизменяемыми
user_id/purpose/token_hash и возвращать свежие данные при чтении с блокировкой.

Infrastructure и presentation подключены:

- SQLAlchemy читает и инвалидирует challenges в транзакции UoW.
- У обоих outbox-сообщений явные версионированные сериализаторы, обработчики
  и шаблоны текста/HTML RU/EN. Локальный SMTP и production SES используют один worker.
- PASSWORD_RESET_TTL по умолчанию PT15M; FRONTEND_PASSWORD_RESET_URL задаёт
  доверенный адрес frontend. Production SES требует HTTPS у обеих frontend-ссылок,
  без встроенных credentials, query и fragment.
- POST /v1/auth/password-reset/request принимает email и возвращает общий 202.
- POST /v1/auth/password-reset/confirm принимает только token и после commit
  однократно возвращает пароль. Лишние поля запрещены; неверный токен даёт 400.
- Auth-ответы имеют Cache-Control: no-store. Тела запросов/результатов и токены
  нельзя логировать. Повтор confirm не идемпотентен: потерянный ответ требует
  нового сброса, исходный пароль нельзя восстановить из хеша.
- Атомарные лимиты Redis общие для API workers: request — 10/IP/минуту,
  3/email/15 минут (включая неизвестные email); confirm — 20/IP/минуту.
  429 содержит Retry-After; сбой Redis даёт безопасный 503 до use case.
  Lua-скрипт атомарно меняет счётчики и TTL; Redis удаляет истёкшие корзины.
  В ключах SHA-256 идентификаторов вместо исходных email/IP; это псевдонимизация,
  а не анонимизация.
- Presentation dependencies также ограничивают login (30/IP/минуту,
  10/нормализованный username/минуту) и регистрацию (10/IP/час,
  3/нормализованный email/час). Значения настраиваются в Settings/.env.
  Учитываются все допущенные попытки, включая успешный вход, неверные credentials
  и конфликт регистрации. Для известных/неизвестных идентификаторов правила
  одинаковы. Лимиты остаются вне auth-обработчиков.
- Успешный request ожидает до 500–600 мс с начала use case. Это сглаживает
  быстрый путь неизвестного аккаунта, но не гарантирует одинаковое время под
  нагрузкой. Политики proxy/body/logging всё равно настраиваются при развёртывании.
- Frontend читает/удаляет fragment URL и подтверждает только по явному действию
  пользователя. Нужны HTTPS, отсутствие аналитики/сторонних скриптов на странице
  сброса, однократный показ пароля и отсутствие его постоянного хранения.

Отзыв сессий прекращает refresh. Для немедленного отклонения ранее выданных
access JWT дополнительно нужна авторизация access-токена с проверкой сессии.

<a id="en"></a>

## English

`RequestPasswordResetUseCase.execute(RequestPasswordResetCommand)` returns None
for both unknown and eligible accounts. Only active accounts with an existing
password receive a PASSWORD_RESET challenge and SendPasswordResetConfirmation
message. User credentials, sessions and previous links remain unchanged until
a valid reset is confirmed. Token generation/hashing also runs for unknown
accounts; this does not guarantee uniform HTTP response timing.

`ConfirmPasswordResetUseCase.execute(ConfirmPasswordResetCommand)` returns
ConfirmPasswordResetResult.password once after commit and successful UoW exit.
The input contains only the reset token. The generated RawPassword is hashed
with IPasswordHasher; only the hash is saved on User. The transaction consumes
the challenge, revokes sessions, invalidates all remaining unused PASSWORD_RESET
challenges for the user and adds SendPasswordChangedNotification without a password.
Missing, expired, consumed, wrong-purpose or ineligible resets raise the same
InvalidPasswordResetTokenError. Infrastructure failures propagate normally.

Reset reads challenge identity without a lock, locks the user, then re-reads
the challenge FOR UPDATE. All reset creation/confirmation paths serialize on
the user lock. Registration confirmation rejects reset-purpose challenges
before acquiring the user lock, avoiding an inverted lock order. Repository
adapters must keep challenge user_id/purpose/token_hash immutable and return
fresh state on locked reads.

Infrastructure and presentation are connected:

- SQLAlchemy challenge reads and invalidation use the UoW transaction.
- Both new outbox messages have explicit versioned serializers, handlers and
  RU/EN text/HTML templates. Local SMTP and production SES use the same worker.
- PASSWORD_RESET_TTL defaults to PT15M; FRONTEND_PASSWORD_RESET_URL determines
  the trusted frontend link target. Production SES requires both frontend URLs
  to use HTTPS, without embedded credentials, queries or fragments.
- POST /v1/auth/password-reset/request accepts email and returns generic 202.
- POST /v1/auth/password-reset/confirm accepts only token and returns password
  once after commit. Extra fields are rejected; invalid tokens map to 400.
- Auth responses use Cache-Control: no-store. Never log request/result/token
  bodies. Repeated confirm is not idempotent: a lost response requires a new
  reset; plaintext cannot be recovered from a hash.
- Redis atomic rate limits are shared across API workers: request IP
  10/minute, email 3/15 minutes (including unknown emails), confirmation IP
  20/minute. 429 includes Retry-After; Redis outages return safe 503 before the
  use case. An atomic Lua script updates counters and TTL; Redis expires buckets.
  Redis keys store SHA-256 identifier digests, not raw
  email/IP; these digests are pseudonymous, not anonymous.
- Presentation dependencies also limit login (30/minute per IP and 10/minute per
  normalized username) and registration (10/hour per IP and 3/hour per normalized
  email). These defaults are configurable in Settings/.env. All admitted attempts,
  including successful logins, invalid credentials and registration conflicts, count.
  Known and unknown identifiers use the same rules. Limits remain outside auth handlers.
- A successful request waits until 500–600 ms after the use case began. This
  reduces the fast unknown-account path but does not guarantee uniform timing
  under load. Proxy/body/logging policy must still be configured at deployment.
- The frontend reads/removes the URL fragment and confirms only on explicit
  user action. It must use HTTPS, exclude analytics/third-party scripts on the
  reset page, show the generated password once and avoid persistent storage.

Session revocation prevents refresh. Immediate rejection of previously issued
access JWTs additionally requires session-bound access-token authentication.

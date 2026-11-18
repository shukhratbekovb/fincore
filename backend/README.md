# FinCore backend / Бэкенд FinCore

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

Требуются Python 3.13+ и Poetry 2.4+. Тестовые зависимости находятся в группе
`test`, точные версии зафиксированы в `poetry.lock`.

Из каталога `backend`:

```bash
poetry install --with test
make test
make test-unit
make test-integration
make test-cov
```

Из корня репозитория: `make -C backend test-cov`.

### Структура

```text
tests/
├── conftest.py                 # общее фиксированное время, автоматические маркеры
├── unit/
│   ├── domain/
│   │   ├── user/
│   │   ├── session/
│   │   └── verification/
│   └── application/
│       └── auth/
└── integration/
    ├── api/                   # приложение FastAPI через HTTPX ASGITransport
    └── persistence/           # интеграционные тесты на PostgreSQL
```

Все каталоги тестов — Python-пакеты. Маркеры `unit` и `integration` назначаются
по расположению файла, включая существующие unittest-классы.

### Запуск и покрытие

```bash
poetry run pytest --collect-only
make test ARGS="-v tests/unit/application/auth/test_refresh.py"
make test ARGS="-k logout"
```

`make test-cov` считает покрытие строк и ветвлений всего `src/backend`, исключая
только `__init__.py`, и завершится ошибкой при результате ниже **91%**.
Непокрытые модули остаются в отчёте. Обычный `make test` запускает тесты без
измерения покрытия. HTML-отчёт: `backend/htmlcov/index.html`.

Pytest добавляет `src` в путь импорта автоматически. Обычные `async def`
тесты и async fixtures запускаются pytest-asyncio в режиме `auto`, с отдельным
циклом событий для каждого теста. Существующие `unittest.TestCase` и
`unittest.IsolatedAsyncioTestCase` также поддерживаются. Неизвестный маркер,
ошибка конфигурации или RuntimeWarning приводят к ошибке прогона.

### Границы проверок

Unit-тесты application используют моки репозиториев и UoW. Они проверяют решения
use case, параметры операций и отсутствие commit при ошибках, но не доказывают
SQL rollback и блокировки.

Integration/API проверяет работающие `/health` и OpenAPI через приложение с
запуском lifespan. Auth router подключён в основном приложении под `/v1/auth`.
HTTP-тесты с подменёнными use cases проверяют контракты auth-эндпоинтов,
обработку ошибок, валидацию и отсутствие секретов в ответах об ошибке.
Отдельный тестовый FastAPI проверяет передачу IP/User-Agent и доверие proxy headers.
Отдельные persistence-тесты проверяют реальные сценарии auth, resend, ротации сессий и сброса пароля с PostgreSQL, Redis и Mailpit.

Unit и HTTP-тесты не требуют сети, БД или почты. Тесты persistence запускаются
на отдельной PostgreSQL при явном FINCORE_TEST_DATABASE_URL; иначе они пропускаются.
Они создают и удаляют отдельную случайную схему для каждого теста, не используя
рабочий DATABASE_URL. Подробности в tests/integration/persistence/README.md.

### Генерация номера кошелька

`RandomWalletNumberGenerator` в `infrastructure/wallet/number_generator.py`
реализует синхронный `WalletNumberGenerator`: генерирует 20 ASCII-цифр через
`secrets`, сохраняя ведущие нули. Генератор не обращается к БД и выдаёт кандидата,
а не гарантию уникальности.

В `CreateWalletUseCase` реализация передаётся как `number_generator`.
При `WalletNumberAlreadyExistsError` из add/commit use case повторяет создание
с новым номером, не более трёх попыток (`max_number_attempts`). Предыдущая
транзакция должна быть полностью отменена при выходе из UoW; новый вход начинает
новую транзакцию и повторно проверяет текущий статус пользователя. Другие ошибки
не повторяются.

Модель и миграция обеспечивают глобальный UNIQUE(number). UoW преобразует
только конфликт uq_wallets_number в WalletNumberAlreadyExistsError. Коллизия,
повтор всей транзакции и отсутствие лишних записей проверены на PostgreSQL.

### Домен LedgerAccount

Модуль `domain/ledger_account` содержит сущность, `LedgerAccountCode`,
`AccountType`, `AccountStatus` и доменные ошибки. Фабрики:

- `LedgerAccount.for_wallet(wallet_id=..., currency=..., now=...)` создаёт
  `LIABILITY` с кодом `WALLET:<uuid>:<currency>`.
- `LedgerAccount.for_sandbox_funding(currency=..., now=...)` создаёт системный
  `ASSET` с кодом `SYS:SIM_FUNDING:<currency>` без привязки к кошельку.

Конструктор также проверяет согласованность полей при восстановлении из БД.
Код ограничен 80 ASCII-символами, время должно содержать часовой пояс.
Сущность использует frozen dataclass без изменяемых общих dataclass-mixins:
учётные реквизиты неизменяемы, только `close()` контролируемо меняет статус.
`close()` идемпотентен; `ensure_active()` отклоняет закрытый счёт. Перед posting
проверка статуса выполняется под защитой транзакции. Проверка допустимости
закрытия по балансу/политике принадлежит будущему application-сценарию.

Баланс и проводки не хранятся в этой сущности. Валюты существующего проекта
сохранены. Модель и миграция обеспечивают уникальный code, один счёт на кошелёк,
соответствие валюты кошельку через составной FK и корректное назначение счёта
через CHECK. Репозиторий при save обновляет только status. Прямые UPDATE в обход
репозитория пока не запрещены отдельной ролью БД или триггерами.

### WalletBalance и создание кошелька

`WalletBalance` наследует `TimeActionMixin` и `BaseEntity`; его идентификатор —
`wallet_id`, отдельный UUID не создаётся. `posted_minor` — целое число минимальных
единиц валюты кошелька, `available_minor` вычисляется из него, `version` начинается
с нуля и увеличивается после каждого успешного credit/debit. Суммы и версии
ограничены диапазоном неотрицательного signed BIGINT. Методы отклоняют дробные,
булевы и неположительные суммы, недостаток средств, переполнение и время без
часового пояса, не изменяя объект при отказе.

Credit/debit меняют только проекцию: posting-сценарий обязан блокировать
баланс и сохранять изменения вместе с ledger entries. Публичного API для прямого
пополнения/списания этой проекции нет.

`CreateWalletUseCase` теперь требует `clock: IClock`. В одной транзакции он
сохраняет Wallet, WalletBalance с нулевой суммой и версией, а также соответствующий
LIABILITY LedgerAccount, затем делает один commit. Нулевые ledger entries не
создаются. UoW дополнен `wallet_balances` и `ledger_accounts`; SQL-реализации
должны использовать одну транзакцию и откатывать все три записи при ошибке.
При конфликте номера повтор создаёт все три объекта заново. Проверки application используют моки;
дополнительно тесты persistence проверяют создание, повтор после коллизии,
откат при FK-ошибке, переименование и закрытие на PostgreSQL.

### Настройки БД и Unit of Work

`infrastructure/settings.py` использует pydantic-settings. Переменные окружения
имеют приоритет над `backend/.env`; путь к файлу не зависит от текущего каталога.
Образец параметров находится в `backend/.env.example`. Существующий `.env` не
перезаписывается. Обязателен `DATABASE_URL` вида
`postgresql+asyncpg://user:password@host:5432/database`; URL хранится как SecretStr.
Дополнительно доступны DATABASE_POOL_SIZE, DATABASE_MAX_OVERFLOW и
DATABASE_POOL_TIMEOUT. Пароль со специальными символами в URL нужно URL-кодировать.

Для всех локальных сервисов используйте `make infra` из backend; `make postgres`,
`make redis` и `make mailpit` запускают их по отдельности. Корневой
`compose.dev.yml` запускает PostgreSQL, Redis и Mailpit; API и worker работают
на хосте через Poetry. PostgreSQL использует postgres:17-alpine в контейнере
fincore-postgres: база/пользователь fincore, адрес 127.0.0.1:55432.
Пароль берётся из FINCORE_POSTGRES_PASSWORD в `.env` и должен совпадать с
паролем в DATABASE_URL. Данные хранятся в постоянном Docker volume
fincore-database_postgres_data. Команда `make infra-down` останавливает локальные
сервисы с сохранением данных. Затем примените миграции
`poetry run alembic upgrade head`. Изменение переменной пароля не меняет
пароль уже инициализированной базы.

Lifespan приложения создаёт один AsyncEngine и `async_sessionmaker`, сохраняет
их в `app.state.engine` и `app.state.session_factory`, а при завершении вызывает
`engine.dispose()`. Подключения открываются лениво, поэтому `/health` не является
проверкой готовности PostgreSQL. В соединениях устанавливается timezone UTC,
включена проверка pool_pre_ping; SQL-параметры скрыты в диагностике SQLAlchemy.
Импорт модулей не читает настройки и не создаёт engine.

Сборка UoW внутри HTTP-запроса:

```python
uow = SqlAlchemyUnitOfWork(request.app.state.session_factory)
```

Один UoW используют в одном выполняющемся сценарии. Каждый `async with uow`
получает новую сессию и репозиторий пользователей. Сохранение явно выполняется
через `await uow.commit()`. При выходе всегда выполняется rollback оставшихся
изменений, затем close в finally; сессия и ссылка на репозиторий очищаются.
Повторный последовательный вход поддерживается, вложенный вход отклоняется.

UoW подключает users, sessions, refresh_tokens, verification_challenges, wallets,
wallet_balances, ledger_accounts и outbox через одну сессию. Конфликты ix_users_email,
ix_users_username и uq_wallets_number с SQLSTATE 23505 преобразуются в соответствующие
application-ошибки после очистки; остальные ошибки целостности сохраняются.
Репозитории не выполняют commit/rollback самостоятельно. Блокирующие чтения
используют FOR UPDATE и populate_existing. Save выполняет UPDATE с RETURNING,
не создаёт отсутствующую запись и не изменяет неизменяемые реквизиты.

Outbox сохраняет задание с версионированным типом и JSONB payload в общей
транзакции. Реестр сериализаторов расширяется через параметр serializers у
SqlAlchemyOutbox; неизвестный тип отклоняется. Отдельный outbox worker доставляет
письмо по SMTP и очищает секретный payload после передачи SMTP-серверу.

Начальная миграция: migrations/versions/20261104_01_initial.py. Для пустой БД:

```bash
poetry run alembic upgrade head
```

Alembic читает URL через Settings и поддерживает asyncpg. Рабочую БД автоматически
при запуске приложения не мигрируем. Проверки миграции выполняют upgrade,
downgrade и сравнение схемы с моделями в отдельной тестовой схеме PostgreSQL.

### Стиль SQLAlchemy-репозиториев

Образец — UserRepository. В каждом модуле сущности используются явные функции
`_to_entity` и `_to_model`, полные имена ORM-моделей и перечисление полей без
рефлексии dataclasses. В методах репозитория явно записываются stmt, execute и
обработка результата. Базовый репозиторий хранит только сессию. Outbox сохраняет
тот же стиль маппинга, используя реестр сериализаторов для разных типов сообщений.

### JWT access-токены

`JWTTokenIssuer` получает Settings через конструктор:

```python
issuer = JWTTokenIssuer(get_settings())
access_token = issuer.encode(user.id)
user_id = issuer.decode(access_token)
```

Для него нужен JWT_SECRET_KEY длиной не менее 32 байт; используйте случайный
секрет, например `secrets.token_urlsafe(32)`. DB-only настройки допускают его
отсутствие, но конструктор JWTTokenIssuer в таком случае выдаёт ошибку конфигурации.
Settings хранит ключ как SecretStr. Поддержан алгоритм HS256 с явным whitelist.
JWT_ACCESS_TOKEN_TTL_MINUTES задаёт срок в минутах (по умолчанию 30); старое имя
JWT_ACCESS_EXPIRES_AT для этой настройки не используется. JWT_ISSUER/JWT_AUDIENCE
по умолчанию fincore/fincore-api.

В токене содержатся sub (UUID), iat, nbf, exp, iss, aud, уникальный jti и
`token_type=access`. Decode проверяет подпись и обязательные claims; истёкший
токен вызывает AccessTokenExpiredError, остальные невалидные токены —
InvalidAccessTokenError. AccessTokenExpiredError является его подклассом.
Пароли и refresh-токены в JWT не помещаются. Refresh остаётся opaque-токеном
с отдельной записью в БД. Decode не обращается к БД: состояние пользователя и
отзыв сессии должны проверяться отдельно при авторизации запроса.

### Срок подтверждения регистрации

`Settings.verification_confirmation_ttl` имеет тип timedelta, по умолчанию один
час. Переменная `VERIFICATION_CONFIRMATION_TTL=PT1H` задаёт ISO 8601 duration;
нулевой и отрицательный срок отклоняются. Dependency get_register_use_case
получает SettingsDep и передаёт срок в RegisterUserUseCase без преобразований.
Вызов сборки синхронный: dependency объявлена через def.

### IP и User-Agent за Nginx

`ClientInfoDep` из `presentation/api/v1/dependencies/client.py` возвращает
неизменяемый DTO `ClientInfo`. IP берётся из `request.client.host`, User-Agent —
из заголовка `User-Agent` (при отсутствии — None). Если ASGI-сервер не передал
client, запрос отклоняется с HTTP 400. Login и refresh передают эти значения
в application-команды; JSON body не задаёт IP или User-Agent.
User-Agent управляется клиентом и служит описанием устройства, а не доказательством
его идентичности.

Dependency не разбирает `X-Forwarded-For` и `X-Real-IP`. Доверие к прокси
настраивается в Uvicorn. Для схемы **клиент → единственный публичный Nginx →
Uvicorn на том же сервере** добавьте в server-блок Nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

На этой границе Nginx перезаписывает полученный от клиента X-Forwarded-For
адресом TCP-соединения. User-Agent передаётся стандартным проксированием заголовков.
Это фрагмент существующего server-блока, не полный конфиг TLS/виртуального хоста.
Он описывает прямую схему Nginx → API; для текущей Docker-схемы с Next.js gateway
следуйте [инструкции VPS](../docs/deployment.md).

Из каталога backend запустите `make serve`. Он запускает Uvicorn без reload,
слушает только 127.0.0.1:8000 и включает proxy headers с доверенным адресом
127.0.0.1. Для разработки без Nginx `make dev` отключает proxy headers.

В Docker нужен адрес или выделенная доверенная сеть Nginx вместо 127.0.0.1;
порт backend должен быть доступен только прокси. Не задавайте `*` как список
доверенных адресов. При появлении CDN/LB перед Nginx сначала настройте доверие
к нему в Nginx Real IP: иначе $remote_addr будет адресом CDN/LB.

Документация: [Uvicorn proxy headers](https://uvicorn.dev/settings/#http),
[Nginx proxy_set_header](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header).

### HTTP-контракт авторизации

Перечисленные эндпоинты находятся под `/v1/auth` и принимают JSON через POST:

| Путь        | Успех             | Ожидаемые ошибки                                                                                        |
| ----------- | ----------------- | ------------------------------------------------------------------------------------------------------- |
| `/register` | 201, user_id      | 409 конфликт, 422 валидация                                                                             |
| `/login`    | 200, пара токенов | 400 нет IP, 401 неверные данные, 403 неактивен, 422 валидация                                           |
| `/refresh`  | 200, пара токенов | 400 нет IP, 401 неверный/истёкший/повторный токен, 403 неактивен, 422 валидация                         |
| `/logout`   | 204, без тела     | 422 валидация                                                                                           |
| `/confirm`  | 204, без тела     | 400 неверный/истёкший/использованный токен, 404 нет пользователя, 409 неверное состояние, 422 валидация |

Ожидаемые ошибки преобразуются обработчиками presentation в единый JSON:

```json
{
  "detail": {
    "code": "invalid_credentials",
    "message": "Invalid username or password",
    "errors": []
  }
}
```

При валидации errors содержит loc, message и type; исходные input/ctx и тело
запроса не возвращаются. Неожиданные исключения остаются HTTP 500.
Входящий username ограничен 5–256 символами и доменным форматом, токены —
1–512 символами без пробельных символов. Login принимает пароль длиной
1–256 символов через PasswordCandidate и проверяет его по хешу без новой
политики сложности. Confirm использует RawPassword с текущей политикой
создания пароля (8–256 символов, верхний/нижний регистр, цифра, спецсимвол).

### Документация ReDoc: RU / EN

После запуска `make dev` доступны:

- `http://127.0.0.1:8000/redoc/ru` — русская документация.
- `http://127.0.0.1:8000/redoc/en` — английская документация.
- `/redoc` — перенаправление на RU.
- `/openapi/ru.json` и `/openapi/en.json` — соответствующие OpenAPI-схемы.
- `/openapi.json` и Swagger `/docs` — английская версия схемы.

Сверху ReDoc есть переключатель RU / EN и ссылка на JSON-схему. Переведены
сценарии, описания эндпоинтов, схем, полей и ответов. Служебные надписи самого
ReDoc (Responses, Request samples и т. п.) остаются стандартными английскими.
Язык документации не меняет реальные сообщения API. Скрипт ReDoc загружается
с CDN; для отображения нужен доступ к нему и JavaScript в браузере.

Исходники находятся в `src/backend/presentation/api/documentation`:

- `content/{ru,en}/overview.md` — общий сценарий, токены, сроки и справочник ошибок.
- `content/{ru,en}/{register,confirm,login,refresh,logout,health}.md` — подробности операций и curl-примеры.
- `content/{ru,en}/metadata.json` — переводы кратких описаний, ответов, моделей и полей.
- `openapi.py` — копирование базовой схемы FastAPI, переводы и общие JSON-примеры.
- `router.py` — страницы ReDoc, переключатель и выдача схем.

Новый эндпоинт и его модели сначала описываются в коде. Затем добавьте операцию
в OPERATIONS, Markdown и метаданные в обеих локалях; примеры — в общие таблицы
в openapi.py. Не копируйте целую OpenAPI-схему вручную и не меняйте идентификаторы
или поля ради перевода. Тесты проверяют одинаковые контракты, наличие переводов,
примеры, отсутствие тела у 204 и работу под proxy root_path.

Схемы кешируются отдельно для каждого языка; при обновлении базовой схемы FastAPI
переводы пересобираются. Изменение файлов переводов требует перезапуска процесса.
Markdown/JSON включены в wheel и sdist, поэтому документация работает после установки пакета.

### Доставка подтверждения: локальный SMTP и Amazon SES

Из каталога backend после настройки рабочего DATABASE_URL в `.env`:

```bash
poetry install --with test
poetry run alembic upgrade head
make mailpit
make dev
```

В отдельном терминале выполните `make worker`. `make worker-once` обрабатывает
одну доступную пачку и завершается. API и worker используют одну PostgreSQL.
Локально SMTP по умолчанию находится на 127.0.0.1:1025, интерфейс Mailpit —
http://127.0.0.1:8025. Mailpit перехватывает письма и не отправляет их реальным
получателям. Остановка всех локальных сервисов: `make infra-down`;
только Mailpit: `docker compose --env-file .env -f ../compose.dev.yml stop mailpit`.

Вызовите POST `/v1/auth/register` с уникальными username/email. Worker отправит
письмо в Mailpit. Ссылка имеет вид FRONTEND_CONFIRMATION_URL#token=...;
страница фронтенда должна извлечь fragment и отправить token/password на
POST `/v1/auth/confirm`. Реализация этой страницы не входит в backend.
Без неё можно вручную передать токен из письма в confirm через Swagger.

Настройки SMTP и worker перечислены в `.env.example`; EMAIL_LOCALE выбирает
русское или английское письмо для всего worker, независимо от языка ReDoc.
Шаблоны subject/text/HTML хранятся в infrastructure/notifications/templates.
Пароли не отправляются по почте. HTML экранируется Jinja2.

Для production задайте SMTP_BACKEND=ses, региональный SMTP_HOST SES,
SMTP_PORT=587, SMTP_SECURITY=starttls, SMTP_USERNAME, SMTP_PASSWORD,
SMTP_FROM_EMAIL подтверждённого домена, HTTPS FRONTEND_CONFIRMATION_URL
и HTTPS FRONTEND_PASSWORD_RESET_URL.
Альтернатива: SMTP_PORT=465 и SMTP_SECURITY=tls. Используйте именно SES SMTP
credentials, а не AWS API access keys. Worker проверяет наличие credentials,
TLS и HTTPS-ссылки. Сертификаты SMTP всегда проверяются. Эти настройки не
создают AWS-ресурсы: домен/отправитель, production access SES и лимиты
необходимо настроить в AWS. Библиотека boto3 для SES SMTP не нужна.

В production worker запускается отдельным процессом под вашим supervisor
или контейнерным оркестратором. SIGINT/SIGTERM останавливают получение новых
заданий; начатые задачи завершаются. Общий предел отправки — OUTBOX_SEND_TIMEOUT,
который должен быть меньше lease минимум на пять секунд.

Очередь использует короткие транзакции с FOR UPDATE SKIP LOCKED, leases и
уникальным lock_token. SMTP вызывается вне транзакции. Attempts увеличивается
при захвате; после сбоя задача доступна по истечении lease. Retry использует
ограниченный exponential backoff с jitter и сохраняет исходный токен.
SMTP 4xx/сетевые ошибки повторяются, SMTP 5xx считаются постоянными.
Неизвестные типы и некорректные payload переводятся в failed.

Статус sent означает принятие письма SMTP-сервером, а не попадание во входящие.
Сбой между отправкой и фиксацией результата может привести к повторному письму;
стабильный Message-ID не гарантирует дедупликацию получателем. По истечении
подтверждения отправка прекращается. В sent/failed/expired payload очищается
до SQL NULL, остаются только технические метаданные. Повторная отправка после
окончательного failed требует нового подтверждения; используйте `POST /v1/auth/confirm/resend` для новой регистрационной ссылки.
Откат миграции 20261105_02 удаляет технические записи с уже очищенным payload.

Интеграционные тесты очереди требуют FINCORE_TEST_DATABASE_URL с базой *_test.
Сквозной тест register → worker → SMTP → confirm дополнительно требует
FINCORE_TEST_SMTP_PORT и FINCORE_TEST_MAILPIT_URL одноразового Mailpit.

### Сброс пароля с автоматической генерацией

Примените миграции: `poetry run alembic upgrade head` и запустите Redis через
`make redis`. Лимиты запросов общие для процессов API и хранятся в Redis.
Настройки добавлены в `.env.example`:

```dotenv
PASSWORD_RESET_TTL=PT15M
FRONTEND_PASSWORD_RESET_URL=http://localhost:3000/reset-password
REDIS_URL=redis://127.0.0.1:56379/0
REDIS_CONNECT_TIMEOUT=1
REDIS_SOCKET_TIMEOUT=1
REDIS_MAX_CONNECTIONS=20
```

API и worker запускаются прежними командами `make dev` и `make worker`.
Сценарий:

1. `POST /v1/auth/password-reset/request` с `{"email":"alice@example.com"}`.
   Ответ — одинаковый `202` для любого корректного email. Для активного пользователя
   с установленным паролем сохраняется outbox-задание на письмо.
2. Worker доставляет ссылку `FRONTEND_PASSWORD_RESET_URL#token=...`. GET не меняет
   пароль. Frontend должен прочитать и удалить fragment, затем после явного
   подтверждения отправить `POST /v1/auth/password-reset/confirm` с `{"token":"..."}`.
3. После commit API возвращает `200 {"password":"..."}`. Пароль генерируется сервером,
   удовлетворяет RawPassword и показывается один раз. Ответ имеет `Cache-Control: no-store`.
   Если ответ потерян, нужен новый запрос сброса. Вход с новым паролем — через `/login`.
4. В той же транзакции отзываются все сессии и остальные reset-ссылки. Worker
   отправляет уведомление о смене пароля **без пароля**. Уже выданные access JWT
   действуют до истечения срока: текущий HTTPBearer не проверяет сессию в БД.

Сброс ограничен через Redis: request — 10/минуту на IP и 3/15 минут на email
(включая неизвестный); confirm — 20/минуту на IP. `429` содержит `Retry-After`.
Lua-скрипт атомарно проверяет бюджет, увеличивает счётчик и устанавливает TTL.
Окно начинается с первого запроса; последующие запросы и отказы не продлевают его.
Просроченные ключи удаляет Redis. Ключи содержат SHA-256, а не исходные IP/email;
доступ к ним всё равно должен быть ограничен. Успешный request ожидает минимум 500–600 мс от начала
use case, чтобы уменьшить разницу между известными и неизвестными аккаунтами;
это не гарантия одинакового времени при любой нагрузке.

`IRateLimiter` находится в application/share/interfaces, реализация RedisRateLimiter —
в infrastructure/security/rate_limiter.py. Правила остаются в FastAPI dependencies;
общий RateLimiterDep возвращает экземпляр из app.state. Lifespan создаёт один
Redis client/pool на процесс и закрывает его при остановке. Автоматические повторы
Redis-команд отключены: потерянный ответ мог последовать за уже увеличенным счётчиком.
Socket/connect timeouts и размер пула задаются настройками выше. Клиент подключается
лениво; при недоступном Redis защищённые запросы получают безопасный
`503 rate_limiter_unavailable`, use case не выполняется, обхода лимитов нет.

Локальный compose публикует Redis только на 127.0.0.1:56379, использует постоянный
том, AOF и noeviction. Это настройки разработки; в production используйте закрытую
сеть, Redis ACL/credentials и rediss:// с проверкой сертификата при TLS.
REDIS_URL хранится как SecretStr; query/fragment запрещены, чтобы URL не переопределял
timeouts и политику подключения. Все процессы API должны использовать одну Redis DB
и одинаковые правила. Потеря Redis-данных сбрасывает временные бюджеты запросов.

Миграция 20261114_05 удаляет прежнюю таблицу auth_rate_limits. Исторические миграции
сохранены; rollback восстанавливает пустую SQL-таблицу. При переключении хранилища
окна запросов начинаются заново, старые счётчики не переносятся. Сначала подготовьте
Redis и новый API; удалять таблицу нужно после остановки всех старых API-процессов.
Денежные лимиты и идемпотентность финансовых операций продолжают использовать PostgreSQL.

Redis integration tests запускаются с FINCORE_TEST_REDIS_URL отдельного тестового
Redis (например redis://127.0.0.1:56380/15); без переменной они пропускаются.
Каждый тест использует уникальный prefix и удаляет только собственные ключи.
Сквозной reset-тест дополнительно требует тестовые PostgreSQL и Mailpit.

### Лимиты login, регистрации и переводов

Redis limiter также подключён через dependencies к POST /v1/auth/login,
POST /v1/auth/register и POST /v1/transfers. Значения по умолчанию:

| Маршрут           | Бюджет IP     | Дополнительный бюджет               |
| ----------------- | ------------- | ----------------------------------- |
| Login             | 30 за минуту  | 10 за минуту на username            |
| Регистрация       | 10 за час     | 3 за час на email                   |
| Создание перевода | 100 за минуту | 30 за минуту на пользователя из JWT |

Настройки в `.env`:

```dotenv
LOGIN_RATE_LIMIT_IP_PER_MINUTE=30
LOGIN_RATE_LIMIT_USERNAME_PER_MINUTE=10
REGISTER_RATE_LIMIT_IP_PER_HOUR=10
REGISTER_RATE_LIMIT_EMAIL_PER_HOUR=3
TRANSFER_RATE_LIMIT_USER_PER_MINUTE=30
TRANSFER_RATE_LIMIT_IP_PER_MINUTE=100
```

Это настраиваемый стартовый профиль; значения нужно согласовывать с продуктом и
нагрузкой. Все процессы API используют одинаковые настройки и Redis. Окно начинается
с первой попытки; аккаунт не блокируется навсегда, успешный login не сбрасывает счётчик.
Username/email приводятся к нижнему регистру по правилам домена; известные и
неизвестные аккаунты имеют одинаковый бюджет. Смена IP не сбрасывает бюджет идентификатора.
IP берётся из ClientInfoDep с существующей политикой доверенных proxy.

Проверяется сначала IP, затем username/email/user_id. Если второй бюджет исчерпан,
первый уже израсходован. Проверки выполняются до use case: неверные credentials,
конфликт регистрации, отказ перевода и успешные операции учитываются как попытки.
У переводов JWT и обязательный Idempotency-Key проверяются до Redis; client-supplied
user_id не определяет бюджет. Один пользователь имеет общий бюджет для всех wallets
и ключей. Повторы завершённого перевода также ограничиваются; после 429 повторяют
тот же ключ и payload. Идемпотентность в PostgreSQL сохраняется, лишнего списания нет.
GET transfers/history/balance не используют этот бюджет. Sandbox top-up сохраняет
собственные проверки доступа; новые правила относятся к трём указанным POST-маршрутам.

Ответы: 429 с Retry-After при превышении любого бюджета; безопасный
503 rate_limiter_unavailable при сбое Redis, без запуска use case. Оба ответа имеют
Cache-Control: no-store. Эти ограничения частоты не заменяют лимиты денежных сумм.
HTTP-контракты и RU/EN документация включают новые ошибки.

Тесты: tests/integration/api/test_rate_limits.py проверяет обе ветки отказа,
настройки, нормализацию и аутентификацию; tests/integration/test_redis_auth_limits.py
проверяет реальные общие бюджеты при смене IP/регистра/Idempotency-Key.
PostgreSQL-тесты дополнительно проверяют, что 429/503 не создают денежные операции,
а разрешённый replay возвращает исходный transfer_id без второго списания.

Production: HTTPS для API и обоих `FRONTEND_*_URL`, доверенные proxy IP в Uvicorn.
Не записывайте тела auth-запросов/ответов в Nginx/APM/аналитику. Страница сброса
должна исключать сторонние скрипты и долговременное хранение пароля. Frontend-страница подключена к этим маршрутам через gateway Next.js.

ReDoc RU/EN содержит оба reset-эндпоинта и `change-password`. Сквозной pytest
`tests/integration/persistence/test_password_reset.py` проверяет PostgreSQL,
SMTP/Mailpit, вход с новым паролем, отклонение старого пароля/refresh, очистку outbox,
конкурентный сброс и полный rollback при ошибке уведомления. Для SMTP используются
те же `FINCORE_TEST_SMTP_PORT` и `FINCORE_TEST_MAILPIT_URL`, что у теста регистрации.

### Профиль и управление своими сессиями

User router подключён с префиксом `/v1/users`. Все четыре маршрута требуют
`Authorization: Bearer <access_token>` и используют user_id из проверенного JWT:

| Метод  | Путь                                 | Ответ                                           |
| ------ | ------------------------------------ | ----------------------------------------------- |
| GET    | `/v1/users/me`                       | `200`, профиль: id, username, email, created_at |
| GET    | `/v1/users/me/sessions`              | `200`, массив активных сессий или `[]`          |
| DELETE | `/v1/users/me/sessions`              | `204`, отзыв всех своих сессий                  |
| DELETE | `/v1/users/me/sessions/{session_id}` | `204`, отзыв одной своей сессии                 |

Сессии отсортированы по created_at DESC, id DESC. Выборка исключает отозванные
и истёкшие записи, включая expires_at == now. Ответы содержат исходные IP/User-Agent
и данные последнего refresh; password hash и токены не возвращаются. Значения
Username/Email преобразуются в строки на границе HTTP. Ответы профиля и сессий
имеют `Cache-Control: no-store`, включая ожидаемые ошибки.

Повторный отзыв собственной сессии безопасен. Отсутствующая и чужая сессии дают
одинаковый `404 session_not_found`. Невалидный UUID — `422`, отсутствующий или
невалидный JWT — `401`, неактивный пользователь — `403`. Оба DELETE возвращают
пустое тело. Отзыв прекращает refresh; ранее выданные access JWT действуют до
истечения срока. `last_used_at` обновляется при refresh, а не при каждом запросе.

### Создание, переименование и закрытие кошелька

Wallet router подключён с префиксом `/v1/wallets`, в стиле auth/user router.
Все операции требуют Bearer access JWT и существующего активного пользователя:

| Метод | Путь                            | Тело                               | Успех                     |
| ----- | ------------------------------- | ---------------------------------- | ------------------------- |
| POST  | `/v1/wallets`                   | `{"name":"Main","currency":"USD"}` | `201 {"wallet_id":"..."}` |
| PATCH | `/v1/wallets/{wallet_id}`       | `{"name":"Savings"}`               | `204`, без тела           |
| POST  | `/v1/wallets/{wallet_id}/close` | Без тела                           | `204`, без тела           |

Валюта по умолчанию — USD, как в существующей CreateWalletCommand. Имя после
удаления пробелов по краям содержит 1–64 символа. В create/rename дополнительные
поля запрещены; user_id берётся из JWT, номер создаёт RandomWalletNumberGenerator.
Create атомарно сохраняет кошелёк, нулевой WalletBalance и liability LedgerAccount.
Коллизии номера повторяются внутри application с откатом между попытками;
исчерпание попыток возвращает `503 wallet_number_unavailable`.

Чужой и отсутствующий кошелёк дают одинаковый `404 wallet_not_found`.
Закрытый кошелёк нельзя переименовать (`409 wallet_closed`). Закрытие с ненулевым
балансом запрещено (`409 wallet_balance_not_zero`); при нулевом балансе закрываются
кошелёк и account, сохраняются баланс и история. Повторное закрытие успешно.
Несогласованное учётное состояние возвращает контролируемый
`500 wallet_accounting_state_error` без внутренних деталей.

Создание не идемпотентно: повторный POST создаёт ещё один кошелёк. Ответы имеют
`Cache-Control: no-store`. GET /v1/wallets и GET /v1/wallets/{wallet_id} подключены к application queries.
Маршруты истории перечислены ниже.
Документация доступна на RU/EN в ReDoc. Новые зависимости и схемы находятся в
`presentation/api/v1/dependencies/wallet.py` и `presentation/api/v1/schemas/wallet.py`.

### Чтение кошельков

`GET /v1/wallets` возвращает массив собственных кошельков с балансами,
`GET /v1/wallets/{wallet_id}` — один собственный кошелёк. Требуется Bearer access JWT.
Идентификатор пользователя берётся из авторизации; query-параметр user_id не
может выбрать чужого владельца. Query проверяет наличие и активность пользователя.

Поддерживаются параметры списка:

- `currency=CAD` — фильтр валюты.
- `status=active` — active, frozen или closed; без параметра включаются все статусы.
- `sort_by=balance:desc` — name/currency/balance/created_at/status и asc/desc.
  По умолчанию created_at:asc, при равных значениях — id ASC.

Например: `/v1/wallets?currency=CAD&status=active&sort_by=balance:desc`.
Пустой результат возвращает `200 []`. Возвращается весь отфильтрованный список;
пагинация пока не добавлена. Сортировка balance сравнивает целые значения minor
без конвертации между валютами.

Ответ содержит id, user_id, name, balance_minor, number, currency, status,
created_at и updated_at. Номер остаётся строкой из 20 цифр, включая ведущие нули;
balance_minor — десятичной строкой целого числа минимальных единиц валюты. updated_at относится к метаданным
кошелька, а не ко времени изменения баланса.

Reader выполняет один SQL SELECT с LEFT JOIN wallet_balances, дополнительно query
читает пользователя. У single-get владельца ограничивает SQL до преобразования
DTO. Отсутствующий и чужой кошелёк дают одинаковый `404 wallet_not_found`.
Если у своего кошелька нет записи баланса, возвращается контролируемый
`500 wallet_accounting_state_error`, без подмены нулём или пропуска кошелька.
Чтение не использует row locks и commit. Ответы имеют `Cache-Control: no-store`.

### Переводы, история и балансы

Подготовленные financial use cases и queries подключены к SQLAlchemy UoW и HTTP:

| Метод | Путь                                   | Обработчик                   |
| ----- | -------------------------------------- | ---------------------------- |
| POST  | `/v1/transfers`                        | `CreateTransferUseCase`      |
| GET   | `/v1/transfers`                        | `GetMyTransfersQuery`        |
| GET   | `/v1/transfers/{transfer_id}`          | `GetTransferQuery`           |
| POST  | `/v1/sandbox/top-ups`                  | `CreateSandboxTopUpUseCase`  |
| GET   | `/v1/wallets/{wallet_id}/transactions` | `GetWalletTransactionsQuery` |
| GET   | `/v1/users/me/transactions`            | `GetMyTransactionsQuery`     |
| GET   | `/v1/wallets/{wallet_id}/balance`      | `GetWalletBalanceQuery`      |
| GET   | `/v1/users/me/balances`                | `GetMyBalanceSummaryQuery`   |

Все маршруты требуют Bearer access JWT, возвращают `Cache-Control: no-store` и
документированы в RU/EN OpenAPI/ReDoc. Actor берётся из JWT. Чужой transfer или
wallet в детальном маршруте возвращает тот же 404, что отсутствующий.

Обе команды требуют `Idempotency-Key`: 1..255 ASCII-символов без пробелов.
Одинаковые actor/scope/key и payload возвращают прежний ID (201); другой payload
даёт 409. Конкурентное ожидание занятого ключа ограничено двумя секундами, затем
возвращается 409 idempotency_in_progress; повторять нужно тот же ключ и payload.
Replay хранится минимум 24 часа. Maintenance по умолчанию архивирует полные записи после семи дней, сохраняя компактные постоянные квитанции для поздних повторов.
Новый ключ означает новую операцию. При отказе или исключении откатывается вся
попытка, включая claim; REJECTED сейчас не сохраняется.

Transfer принимает sender_wallet_id, receiver_wallet_id, amount_minor, currency.
Sandbox принимает wallet_id, amount_minor, currency. На входе amount_minor —
положительный integer либо десятичная строка в пределах signed BIGINT; bool/float
не принимаются. Результаты — transfer_id и top_up_id соответственно.
В новых responses суммы minor units и version возвращаются **строками**, чтобы
JavaScript сохранял точность больших чисел. `WalletResponse.balance_minor` тоже возвращается строкой; UI использует BigInt.

Списки transfers/history возвращают `{items, next_cursor}`; limit=20, максимум 100.
Порядок — created_at/id DESC для transfers, posted_at/id DESC для history.
Подписанный cursor привязан к actor, типу списка и фильтрам. Настройка
PAGINATION_SECRET_KEY необязательна: без неё DI выводит отдельный HMAC-ключ из
JWT_SECRET_KEY. У всех экземпляров API должен быть одинаковый ключ; смена ключа
инвалидирует старые cursors. Даты фильтров требуют timezone, диапазон [from, to).
Полные фильтры и примеры запросов доступны в ReDoc.

История показывает только проведённые journals, внутренний перевод — один раз.
При выборе конкретного кошелька направление рассчитывается относительно него.
Баланс читается также у frozen/closed wallets; spendable у них равен 0.
Summary считает totals отдельно по валютам одним SQL statement; available=posted,
пока нет holds. Отсутствующая проекция своего кошелька — ошибка целостности 500.

Применение миграции:

```bash
poetry run alembic upgrade head
```

Миграция 20261112_04 создаёт transfers, sandbox_top_ups, ledger_transactions,
ledger_entries, idempotency_records и sandbox_operators, а также funding accounts
поддерживаемых валют. PostgreSQL проверяет связи/валюты, уникальный journal,
соответствие проводок операции и баланс пары; проведённые записи неизменяемы.
Балансовые проекции изменяются вместе с journal в одной UoW-транзакции.
Read-only reconciliation реализована отдельной query и CLI; разграничение DB roles остаётся отдельной эксплуатационной задачей.

Sandbox выключен по умолчанию (`SANDBOX_ENABLED=false`). Для локального
пополнения нужны включённый флаг и server-side право активного оператора:

```bash
poetry run python -m backend.bootstrap.sandbox --operator-user-id <USER_UUID>
poetry run python -m backend.bootstrap.sandbox --operator-user-id <USER_UUID> --revoke
```

CLI выдаёт/отзывает разрешение, не меняя SANDBOX_ENABLED; роль из HTTP body
не принимается. `TRANSFER_MAX_AMOUNT_MINOR` и `SANDBOX_MAX_AMOUNT_MINOR`
ограничивают одну новую операцию, default — технический предел signed BIGINT.
Продуктовые дневные/общие лимиты пока отсутствуют.

Проверки `tests/integration/persistence/test_finance_endpoints.py` используют
отдельную тестовую PostgreSQL: все восемь маршрутов, ACL, фильтры/cursors,
конкурентные переводы и ключи, overspending, полный rollback, большие суммы,
выдача/отзыв разрешений и защита журнала. Миграции проверяются upgrade/downgrade
и сравнением схемы с моделями в `test_repositories.py`.

### VPS Docker, health и логи

Frontend подключён к API через серверный gateway Next.js; инструкции запуска,
Mailpit и выдачи sandbox-разрешения: [frontend/README.md](../frontend/README.md).
`WalletResponse.balance_minor` в JSON теперь десятичная строка, как остальные
денежные поля finance API: это сохраняет точность 64-битных значений в JavaScript.

`backend/Dockerfile`, `frontend/Dockerfile` и корневой `compose.yml` запускают Next.js, API, outbox worker, maintenance, PostgreSQL, Redis и отдельный migration job. Настройки берутся из корневого .env, а не backend/.env.
Пошаговый запуск и обновление: [docs/deployment.md](../docs/deployment.md).
На loopback опубликован frontend (по умолчанию 3000); API, PostgreSQL и Redis остаются внутри Docker-сетей. Gateway проверяет секрет ingress и один IP из Nginx, а Uvicorn доверяет только выделенному внутреннему адресу frontend.
Nginx и резервное копирование в этой задаче не настраиваются.

`/health` и `/health/live` отвечают без внешних сервисов. `/health/ready` параллельно
проверяет SELECT 1 PostgreSQL и PING Redis с HEALTH_CHECK_TIMEOUT (по умолчанию
2 секунды, максимум 10), возвращает 200 или безопасный 503. SMTP/SES не проверяется.
Middleware возвращает X-Request-ID и пишет JSON metadata: route template, status,
duration_ms, request_id. Тела, токены и raw URL не читаются и не логируются.
Docker launcher отключает Uvicorn access log, worker использует общий formatter.
Логи направляются в stdout, Docker сохраняет три файла по 10 MB для контейнера.
Внешние метрики и дашборды не устанавливаются.

FreezeWalletUseCase/UnfreezeWalletUseCase доступны через POST
`/v1/wallets/{wallet_id}/freeze` и `/unfreeze`. Только активный owner, ответ 204
идемпотентен; CLOSED возвращает 409. Статус проверяется под общими locks,
баланс/account не меняются. Frozen wallet не допускает новые движения,
но его история и остатки доступны.

Служебная сверка: `python -m backend.bootstrap.reconcile_ledger --sample-limit 10`.
[Reconciliation README](src/backend/application/reconciliation/README.md) описывает
проверки, единый snapshot, ограниченные примеры и exit codes 0/1/2.
Автоматического исправления данных нет.

### Поиск получателя перевода

`POST /v1/transfer-recipients/resolve` принимает `wallet_number` — строку ровно
из 20 ASCII-цифр. `ResolveWalletRecipientQuery` проверяет активность текущего
пользователя и через `IWalletReader.get_recipient_by_number()` получает
`wallet_id`, `number`, `currency`, `owner`. Поле `owner` — username получателя,
владельца найденного кошелька. SQL reader использует уникальный номер и JOIN users;
баланс, email и приватное название кошелька в ответ не включаются.

Поиск доступен по полному номеру активного кошелька активного владельца. Для
неизвестного, замороженного, закрытого кошелька или неактивного владельца ответ
одинаковый: 404 wallet_not_found. Собственные кошельки тоже могут быть найдены.
Query работает без блокировок и commit; создание перевода повторно проверяет
состояние кошельков, валюту, права и баланс. Readiness результата не гарантирует,
что кошелёк останется активным к моменту подтверждения.

Лимиты Redis: RECIPIENT_LOOKUP_RATE_LIMIT_USER_PER_MINUTE=30 и
RECIPIENT_LOOKUP_RATE_LIMIT_IP_PER_MINUTE=100. При недоступном limiter возвращается
503, запрос к reader не выполняется. Номер передаётся в body, ответы имеют no-store.
RU/EN OpenAPI содержит схему и примеры. Frontend показывает логин и валюту найденного
получателя, сбрасывает результат при изменении номера и использует UUID внутри
существующего запроса перевода. В реквизитах кошелька можно скопировать полный номер.

### Повторная отправка подтверждения

`POST /v1/auth/confirm/resend` принимает только `email`, без JWT. При корректном
допущенном запросе ответ `202` одинаков для неизвестных, активных и ожидающих
подтверждения аккаунтов. Только `pending_confirmation` получает новый challenge:
под блокировкой пользователя старые неиспользованные регистрационные ссылки
инвалидируются, новый хеш и outbox сохраняются атомарно. Password-reset challenges
не меняются. Confirm использует тот же порядок блокировок: user → challenge.

Срок ссылки — `VERIFICATION_CONFIRMATION_TTL`. Redis учитывает все попытки:
`RESEND_CONFIRMATION_RATE_LIMIT_IP_PER_HOUR=20` и
`RESEND_CONFIRMATION_RATE_LIMIT_EMAIL_PER_HOUR=3`. Превышение даёт `429` с Retry-After,
недоступный limiter — `503` без выполнения use case. Worker нужен для доставки;
ответ `202` её не гарантирует. Frontend предлагает resend из входа, регистрации
и подтверждения. Контракт, ошибки и примеры доступны в RU/EN OpenAPI/ReDoc.

### Очистка и CI

`make cleanup-preview` показывает кандидатов; `make cleanup` выполняет один проход.
Compose-сервис `maintenance` запускается сразу и затем раз в сутки. Он очищает
истёкшие/отозванные сессии вместе с refresh-цепочками, старые challenges, terminal
outbox и архивирует полные idempotency records. Активные данные и финансовые записи
сохраняются. Политика, batch limits, отчёты и ограничения rollback описаны в
[maintenance](../docs/maintenance.md).

Миграция `20261115_06` добавляет индексы очистки и `idempotency_receipts`.
Постоянные квитанции сохраняют исходный результат и payload hash под SHA-256
идентичности actor/scope/key; они не очищаются по TTL. Поздний повтор возвращает
тот же результат, другой payload — `409`. DB запрещает удаление полного replay
без квитанции и изменение квитанций. После первого архива downgrade запрещён.

[GitHub Actions](../.github/workflows/ci.yml) проверяет весь backend на Python 3.13
и 3.14 с PostgreSQL, Redis и Mailpit без пропусков и с порогом покрытия 91%.
Отдельные jobs проверяют frontend, browser E2E и полный production Docker-стек.
Итоговый `CI required checks` требует успеха всех jobs; отчёты хранятся 14 дней.
[CI guide](../docs/ci.md) описывает окружение и артефакты. Фактический запуск Actions
произойдёт после push; локальные результаты приведены в
[отчёте 17 ноября](../docs/test-report-2026-11-17.md).

<a id="en"></a>

## English

Python 3.13+ and Poetry 2.4+ are required. Test dependencies are in the `test`
group; exact versions are pinned in `poetry.lock`.

From `backend`:

```bash
poetry install --with test
make test
make test-unit
make test-integration
make test-cov
```

From the repository root: `make -C backend test-cov`.

### Structure

```text
tests/
├── conftest.py                 # shared fixed time and automatic markers
├── unit/
│   ├── domain/
│   │   ├── user/
│   │   ├── session/
│   │   └── verification/
│   └── application/
│       └── auth/
└── integration/
    ├── api/                   # FastAPI through HTTPX ASGITransport
    └── persistence/           # PostgreSQL integration tests
```

All test directories are Python packages. The `unit` and `integration` markers
are assigned by file location, including existing unittest classes.

### Running tests and coverage

```bash
poetry run pytest --collect-only
make test ARGS="-v tests/unit/application/auth/test_refresh.py"
make test ARGS="-k logout"
```

`make test-cov` measures line and branch coverage across all of `src/backend`,
excluding only `__init__.py`, and fails below **91%**. Uncovered modules remain
in the report. Plain `make test` runs without coverage measurement.
HTML report: `backend/htmlcov/index.html`.

Pytest adds `src` to the import path automatically. Plain `async def` tests and
async fixtures use pytest-asyncio in `auto` mode, with a separate event loop per
test. Existing `unittest.TestCase` and `unittest.IsolatedAsyncioTestCase` are
supported. Unknown markers, configuration errors and RuntimeWarning fail the run.

### Verification boundaries

Application unit tests use repository and UoW mocks. They check use case decisions,
operation arguments and absence of commits on error; they do not prove SQL rollback
or locking.

Integration/API checks `/health` and OpenAPI through the application with lifespan
started. The auth router is mounted at `/v1/auth`. HTTP tests with substituted use
cases check endpoint contracts, errors, validation and absence of secrets in error
responses. A separate test FastAPI app verifies IP/User-Agent forwarding and proxy
header trust. Persistence tests check actual auth, resend, session rotation and
password-reset flows with PostgreSQL, Redis and Mailpit.

Unit and HTTP tests need no network, database or email. Persistence tests use a
separate PostgreSQL database only when FINCORE_TEST_DATABASE_URL is explicitly set;
otherwise they are skipped. They create/drop a separate random schema per test
and never use the working DATABASE_URL. See
[PostgreSQL test instructions](tests/integration/persistence/README.md).

### Wallet number generation

`RandomWalletNumberGenerator` in `infrastructure/wallet/number_generator.py`
implements synchronous `WalletNumberGenerator`: it generates 20 ASCII digits
through `secrets`, preserving leading zeroes. It does not access the database
and produces a candidate, not a uniqueness guarantee.

It is injected into `CreateWalletUseCase` as `number_generator`. On
`WalletNumberAlreadyExistsError` from add/commit, the use case retries with a
new number, up to three attempts (`max_number_attempts`). The previous transaction
must be fully rolled back when leaving the UoW; reentry starts a new transaction
and rechecks the user's current status. Other errors are not retried.

The model and migration enforce global UNIQUE(number). The UoW translates only
a uq_wallets_number conflict into WalletNumberAlreadyExistsError. PostgreSQL tests
cover collisions, whole-transaction retry and absence of extra records.

### LedgerAccount domain

`domain/ledger_account` contains the entity, `LedgerAccountCode`, `AccountType`,
`AccountStatus` and domain errors. Factories:

- `LedgerAccount.for_wallet(wallet_id=..., currency=..., now=...)` creates
  a `LIABILITY` with code `WALLET:<uuid>:<currency>`.
- `LedgerAccount.for_sandbox_funding(currency=..., now=...)` creates a system
  `ASSET` with code `SYS:SIM_FUNDING:<currency>` and no wallet reference.

The constructor also validates field consistency when restoring from the database.
Codes are limited to 80 ASCII characters and timestamps must be timezone-aware.
The entity is a frozen dataclass without shared mutable dataclass mixins:
accounting identity is immutable; only `close()` changes status in a controlled way.
`close()` is idempotent; `ensure_active()` rejects closed accounts. Posting checks
status under transaction protection. Balance/policy checks for closing belong
to the application workflow.

Balances and entries are not stored in this entity. Existing project currencies
are retained. The model/migration enforce unique code, one account per wallet,
matching wallet currency through a composite FK, and account purpose through CHECK.
Repository save updates only status. Direct UPDATE outside repositories is not
yet prohibited by a dedicated database role or account-specific triggers.

### WalletBalance and wallet creation

`WalletBalance` inherits `TimeActionMixin` and `BaseEntity`; its identity is
`wallet_id`, with no separate UUID. `posted_minor` is an integer number of the
wallet currency's minor units; `available_minor` is derived from it. `version`
starts at zero and increments after each successful credit/debit. Amounts and
versions are bounded by nonnegative signed BIGINT. Methods reject fractional,
boolean and nonpositive amounts, insufficient funds, overflow and naive times
without mutating the object on failure.

Credit/debit updates only the projection: posting must lock the balance and
persist changes together with ledger entries. There is no public API for directly
crediting/debiting this projection.

`CreateWalletUseCase` requires `clock: IClock`. In one transaction it saves Wallet,
a zero WalletBalance/version and the matching LIABILITY LedgerAccount, then commits
once. No zero-value ledger entries are created. UoW exposes `wallet_balances` and
`ledger_accounts`; SQL implementations share one transaction and roll back all
three records on error. A number collision recreates all three objects on retry.
Application checks use mocks; persistence tests also cover creation, collision
retry, FK rollback, renaming and closure on PostgreSQL.

### Database settings and Unit of Work

`infrastructure/settings.py` uses pydantic-settings. Environment variables override
`backend/.env`; the file path is independent of the current directory. Examples
are in `backend/.env.example`. An existing `.env` is not overwritten.
`DATABASE_URL` is required in the form
`postgresql+asyncpg://user:password@host:5432/database` and stored as SecretStr.
DATABASE_POOL_SIZE, DATABASE_MAX_OVERFLOW and DATABASE_POOL_TIMEOUT are also
available. URL-encode special characters in database passwords.

Use `make infra` from backend for all local services; `make postgres`, `make redis`
and `make mailpit` start them individually. Root `compose.dev.yml` starts PostgreSQL,
Redis and Mailpit; API and worker run on the host through Poetry. PostgreSQL uses
postgres:17-alpine in fincore-postgres: database/user fincore, address
127.0.0.1:55432. FINCORE_POSTGRES_PASSWORD in `.env` must match DATABASE_URL.
Data persists in Docker volume fincore-database_postgres_data. `make infra-down`
stops local services while retaining data. Then apply migrations with
`poetry run alembic upgrade head`. Changing the password environment variable does
not change the password of an initialized database.

Application lifespan creates one AsyncEngine and `async_sessionmaker`, stores them
in `app.state.engine` and `app.state.session_factory`, and calls `engine.dispose()`
on shutdown. Connections open lazily, so `/health` is not a PostgreSQL readiness
check. Connections use UTC and pool_pre_ping; SQLAlchemy diagnostics hide SQL
parameters. Imports neither read settings nor create an engine.

Construct a UoW inside an HTTP request:

```python
uow = SqlAlchemyUnitOfWork(request.app.state.session_factory)
```

Use one UoW per executing workflow. Each `async with uow` gets a new session and
user repository. Persist explicitly with `await uow.commit()`. Exit always rolls
back remaining changes, then closes in finally; session/repository references are
cleared. Sequential reentry is supported; nested entry is rejected.

UoW connects users, sessions, refresh_tokens, verification_challenges, wallets,
wallet_balances, ledger_accounts and outbox through one session. Conflicts on
ix_users_email, ix_users_username and uq_wallets_number with SQLSTATE 23505 are
translated into application errors after cleanup; other integrity errors propagate.
Repositories never commit/roll back independently. Locked reads use FOR UPDATE
and populate_existing. Save uses UPDATE with RETURNING, never creates missing
records and never changes immutable identity fields.

Outbox saves a versioned job type and JSONB payload in the shared transaction.
SqlAlchemyOutbox's serializers parameter extends its serializer registry; unknown
types are rejected. A separate worker delivers SMTP email and clears secret
payload after the SMTP server accepts it.

Initial migration: migrations/versions/20261104_01_initial.py. For an empty database:

```bash
poetry run alembic upgrade head
```

Alembic reads the URL through Settings and supports asyncpg. Application startup
does not automatically migrate the database. Migration tests upgrade, downgrade
and compare schema against models in an isolated PostgreSQL test schema.

### SQLAlchemy repository style

UserRepository is the reference. Each entity module uses explicit `_to_entity`
and `_to_model` functions, full ORM model names and explicit fields without
dataclass reflection. Repository methods explicitly define stmt, execute and
result handling. The base repository stores only the session. Outbox follows the
same mapping style, using a serializer registry for different message types.

### JWT access tokens

`JWTTokenIssuer` receives Settings through its constructor:

```python
issuer = JWTTokenIssuer(get_settings())
access_token = issuer.encode(user.id)
user_id = issuer.decode(access_token)
```

JWT_SECRET_KEY must contain at least 32 bytes; use a random secret such as
`secrets.token_urlsafe(32)`. Database-only settings allow it to be absent, but
JWTTokenIssuer then raises a configuration error. Settings stores it as SecretStr.
HS256 is supported through an explicit allowlist. JWT_ACCESS_TOKEN_TTL_MINUTES
sets the lifetime in minutes (default 30); the old JWT_ACCESS_EXPIRES_AT name is
not used. JWT_ISSUER/JWT_AUDIENCE default to fincore/fincore-api.

Tokens contain sub (UUID), iat, nbf, exp, iss, aud, unique jti and
`token_type=access`. Decode checks signature and required claims; expired tokens
raise AccessTokenExpiredError, other invalid tokens raise InvalidAccessTokenError.
AccessTokenExpiredError subclasses InvalidAccessTokenError. Passwords and refresh
tokens are never placed in JWTs. Refresh remains an opaque token with a separate
DB record. Decode does not query the database: user state and session revocation
need separate authorization checks.

### Registration confirmation lifetime

`Settings.verification_confirmation_ttl` is a timedelta, default one hour.
`VERIFICATION_CONFIRMATION_TTL=PT1H` accepts an ISO 8601 duration; zero and negative
values are rejected. The get_register_use_case dependency receives SettingsDep
and passes the duration unchanged into RegisterUserUseCase. Construction is
synchronous: the dependency is declared with def.

### IP and User-Agent behind Nginx

`ClientInfoDep` in `presentation/api/v1/dependencies/client.py` returns immutable
`ClientInfo`. IP comes from `request.client.host`; User-Agent comes from the header
(or None). Missing ASGI client information yields HTTP 400. Login and refresh pass
these values into application commands; JSON bodies do not supply IP/User-Agent.
User-Agent is client-controlled device metadata, not proof of device identity.

The dependency does not parse `X-Forwarded-For` or `X-Real-IP`. Configure proxy
trust in Uvicorn. For **client → one public Nginx → Uvicorn on the same host**,
add this to the Nginx server block:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Nginx overwrites client-supplied X-Forwarded-For with the TCP peer address.
User-Agent passes through normal header proxying. This is a server-block fragment,
not a complete TLS/virtual-host configuration. It describes direct Nginx → API;
for the current Next.js gateway Docker topology, follow
[VPS deployment](../docs/deployment.md).

From backend, `make serve` runs Uvicorn without reload, binds 127.0.0.1:8000 and
enables proxy headers trusted only from 127.0.0.1. For development without Nginx,
`make dev` disables proxy headers.

Docker needs the proxy's address or a dedicated trusted network instead of
127.0.0.1; backend ports must be accessible only to trusted upstreams. Never use
`*` as trusted addresses. If a CDN/LB precedes Nginx, configure Nginx Real IP trust
first, otherwise $remote_addr identifies the CDN/LB.

Documentation: [Uvicorn proxy headers](https://uvicorn.dev/settings/#http),
[Nginx proxy_set_header](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header).

### Authentication HTTP contract

These endpoints live under `/v1/auth` and accept JSON through POST:

| Path        | Success         | Expected errors                                                                     |
| ----------- | --------------- | ----------------------------------------------------------------------------------- |
| `/register` | 201, user_id    | 409 conflict, 422 validation                                                        |
| `/login`    | 200, token pair | 400 missing IP, 401 invalid credentials, 403 inactive, 422 validation               |
| `/refresh`  | 200, token pair | 400 missing IP, 401 invalid/expired/reused token, 403 inactive, 422 validation      |
| `/logout`   | 204, no body    | 422 validation                                                                      |
| `/confirm`  | 204, no body    | 400 invalid/expired/used token, 404 missing user, 409 invalid state, 422 validation |

Presentation handlers map expected errors to a shared JSON format:

```json
{
  "detail": {
    "code": "invalid_credentials",
    "message": "Invalid username or password",
    "errors": []
  }
}
```

Validation errors include loc, message and type, never original input/ctx or the
request body. Unexpected exceptions remain HTTP 500. Username input is limited
to 5–256 characters and the domain format; tokens to 1–512 non-whitespace
characters. Login accepts 1–256-character passwords through PasswordCandidate,
checking the hash without reapplying creation complexity policy. Confirm uses
RawPassword with the current creation policy: 8–256 characters, upper/lowercase,
a digit and a special character.

### ReDoc documentation: RU / EN

After `make dev`:

- `http://127.0.0.1:8000/redoc/ru` — Russian documentation.
- `http://127.0.0.1:8000/redoc/en` — English documentation.
- `/redoc` — redirects to RU.
- `/openapi/ru.json` and `/openapi/en.json` — localized OpenAPI schemas.
- `/openapi.json` and Swagger `/docs` — English schema.

ReDoc has a RU / EN switch and schema JSON link. Flows, endpoint/schema/field/
response descriptions are translated. ReDoc's own interface labels (Responses,
Request samples, etc.) remain English. Documentation language does not change
actual API messages. ReDoc loads its script from a CDN and needs CDN access and
browser JavaScript.

Sources live in `src/backend/presentation/api/documentation`:

- `content/{ru,en}/overview.md` — overall flow, tokens, lifetimes and error reference.
- `content/{ru,en}/{register,confirm,login,refresh,logout,health}.md` — operation details and curl examples.
- `content/{ru,en}/metadata.json` — summary, response, model and field translations.
- `openapi.py` — copies the base FastAPI schema, applies translations and shared JSON examples.
- `router.py` — ReDoc pages, language switch and schema endpoints.

Describe new endpoints/models in code first. Then add the operation to OPERATIONS,
Markdown and metadata in both locales, and shared examples in openapi.py. Do not
manually copy the entire OpenAPI schema or rename identifiers/fields to translate
them. Tests check matching contracts, translations, examples, no body for 204 and
proxy root_path support.

Schemas are cached per language and rebuilt when the base FastAPI schema changes.
Translation file changes need a process restart. Markdown/JSON are included in
wheel and sdist, so documentation works after package installation.

### Confirmation delivery: local SMTP and Amazon SES

From backend, after configuring the working DATABASE_URL in `.env`:

```bash
poetry install --with test
poetry run alembic upgrade head
make mailpit
make dev
```

Run `make worker` in a separate terminal. `make worker-once` processes one available
batch and exits. API and worker use the same PostgreSQL. Local SMTP defaults to
127.0.0.1:1025; Mailpit UI is http://127.0.0.1:8025. Mailpit captures mail without
sending to real recipients. Stop all local services with `make infra-down`, or
only Mailpit with `docker compose --env-file .env -f ../compose.dev.yml stop mailpit`.

Call POST `/v1/auth/register` with a unique username/email. The worker sends a
Mailpit message containing FRONTEND_CONFIRMATION_URL#token=.... The frontend reads
the fragment and sends token/password to POST `/v1/auth/confirm`. This page lives
in frontend, outside backend. Alternatively, submit the emailed token manually
through Swagger.

SMTP/worker settings are listed in `.env.example`; EMAIL_LOCALE selects Russian
or English mail for the entire worker, independently of ReDoc language.
Subject/text/HTML templates live in infrastructure/notifications/templates.
Passwords are not emailed. Jinja2 escapes HTML.

For production, set SMTP_BACKEND=ses, a regional SES SMTP_HOST, SMTP_PORT=587,
SMTP_SECURITY=starttls, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL from a
verified domain, HTTPS FRONTEND_CONFIRMATION_URL and HTTPS FRONTEND_PASSWORD_RESET_URL.
Alternatively, use SMTP_PORT=465 with SMTP_SECURITY=tls. Use SES SMTP credentials,
not AWS API access keys. The worker requires credentials, TLS and HTTPS links;
SMTP certificates are always verified. These settings do not provision AWS
resources: configure domain/sender verification, SES production access and limits
in AWS. boto3 is not needed for SES SMTP.

Run the production worker as a separate process under a supervisor or container
orchestrator. SIGINT/SIGTERM stop taking new jobs and let started jobs finish.
OUTBOX_SEND_TIMEOUT bounds delivery and must be at least five seconds shorter
than the lease.

The queue uses short transactions with FOR UPDATE SKIP LOCKED, leases and unique
lock_token. SMTP runs outside the transaction. Attempts increments on claim;
after failure the job becomes available when its lease expires. Retries use bounded
exponential backoff with jitter and preserve the original token. SMTP 4xx/network
errors retry; SMTP 5xx is permanent. Unknown types and invalid payloads become failed.

sent means SMTP acceptance, not inbox delivery. A crash between sending and saving
the result may duplicate mail; a stable Message-ID does not guarantee recipient
deduplication. Delivery stops after confirmation expiry. sent/failed/expired jobs
clear payload to SQL NULL, retaining only technical metadata. A terminal failed
job requires a new confirmation; use `POST /v1/auth/confirm/resend` for a new
registration link. Downgrading 20261105_02 removes technical records whose payload
was already cleared.

Queue integration tests require FINCORE_TEST_DATABASE_URL with a *_test database.
The register → worker → SMTP → confirm test also requires FINCORE_TEST_SMTP_PORT
and FINCORE_TEST_MAILPIT_URL pointing to disposable Mailpit.

### Password reset with automatic generation

Apply migrations with `poetry run alembic upgrade head` and start Redis using
`make redis`. Redis stores request limits shared by API processes.
Settings in `.env.example`:

```dotenv
PASSWORD_RESET_TTL=PT15M
FRONTEND_PASSWORD_RESET_URL=http://localhost:3000/reset-password
REDIS_URL=redis://127.0.0.1:56379/0
REDIS_CONNECT_TIMEOUT=1
REDIS_SOCKET_TIMEOUT=1
REDIS_MAX_CONNECTIONS=20
```

Start API and worker with `make dev` and `make worker`. Flow:

1. `POST /v1/auth/password-reset/request` with `{"email":"alice@example.com"}`
   returns the same `202` for every valid email. An active user with an existing
   password gets an outbox email job.
2. The worker delivers `FRONTEND_PASSWORD_RESET_URL#token=...`. GET does not change
   the password. Frontend reads/removes the fragment and, after explicit user
   confirmation, sends `POST /v1/auth/password-reset/confirm` with `{"token":"..."}`.
3. After commit, API returns `200 {"password":"..."}`. The server generates a
   RawPassword-compliant password and shows it once. The response has
   `Cache-Control: no-store`. A lost response requires another reset request.
   Sign in with the new password through `/login`.
4. The same transaction revokes all sessions and other reset links. The worker
   sends a password-change notification **without the password**. Issued access
   JWTs remain valid until expiry; current HTTPBearer does not check the DB session.

Redis reset limits: request 10/IP/minute and 3/email/15 minutes, including unknown
emails; confirm 20/IP/minute. `429` includes `Retry-After`. A Lua script atomically
checks the budget, increments the counter and sets TTL. Windows begin with the
first request; later attempts/refusals do not extend them. Redis removes expired
keys. Keys contain SHA-256 digests, not raw IP/email, but still need restricted
access. Successful requests wait until at least 500–600 ms from use case start to
reduce known/unknown account timing differences; this is not uniform timing under
all loads.

`IRateLimiter` lives in application/share/interfaces; RedisRateLimiter is in
infrastructure/security/rate_limiter.py. Rules remain in FastAPI dependencies;
RateLimiterDep returns the instance from app.state. Lifespan creates one Redis
client/pool per process and closes it on shutdown. Automatic command retries are
disabled because a lost response may follow an already incremented counter.
Settings above control socket/connect timeouts and pool size. Connections are lazy;
unavailable Redis causes safe `503 rate_limiter_unavailable` before the use case,
without bypassing limits.

Local Compose publishes Redis only at 127.0.0.1:56379, using a persistent volume,
AOF and noeviction. These are development settings; production needs a private
network, Redis ACL/credentials and rediss:// with certificate validation for TLS.
REDIS_URL is SecretStr; query/fragment are prohibited to prevent overriding timeout
and connection policy through the URL. All API processes need one Redis DB and
identical rules. Redis data loss resets temporary request budgets.

Migration 20261114_05 removes the old auth_rate_limits table. Historical migrations
remain; rollback recreates an empty SQL table. Switching storage starts new windows;
counters are not migrated. Prepare Redis and the new API first; remove the table
only after stopping every old API process. Financial amount limits and idempotency
remain in PostgreSQL.

Redis integration tests use FINCORE_TEST_REDIS_URL for a dedicated test Redis,
e.g. redis://127.0.0.1:56380/15; without it they are skipped. Each test uses a unique
prefix and deletes only its own keys. End-to-end reset also needs test PostgreSQL
and Mailpit.

### Login, registration and transfer limits

Redis dependencies also protect POST /v1/auth/login, POST /v1/auth/register and
POST /v1/transfers. Defaults:

| Route           | IP budget  | Additional budget      |
| --------------- | ---------- | ---------------------- |
| Login           | 30/minute  | 10/minute per username |
| Registration    | 10/hour    | 3/hour per email       |
| Create transfer | 100/minute | 30/minute per JWT user |

Settings in `.env`:

```dotenv
LOGIN_RATE_LIMIT_IP_PER_MINUTE=30
LOGIN_RATE_LIMIT_USERNAME_PER_MINUTE=10
REGISTER_RATE_LIMIT_IP_PER_HOUR=10
REGISTER_RATE_LIMIT_EMAIL_PER_HOUR=3
TRANSFER_RATE_LIMIT_USER_PER_MINUTE=30
TRANSFER_RATE_LIMIT_IP_PER_MINUTE=100
```

These configurable defaults need product/load review. Every API process shares
settings and Redis. A window begins on first attempt; accounts are not permanently
locked, and successful login does not reset counters. Username/email is lowercased
under domain rules; known/unknown accounts share budgets. Changing IP does not
reset the identifier budget. ClientInfoDep supplies IP using existing proxy trust.

IP is checked first, then username/email/user_id. If the second budget is exhausted,
the first has already been consumed. Checks precede use cases: invalid credentials,
registration conflicts, transfer refusals and successes all count. Transfer JWT
and required Idempotency-Key validation precede Redis; client-supplied user_id does
not select the budget. One user shares a budget across wallets and keys. Replays
also count; after 429 retry the same key/payload. PostgreSQL idempotency prevents
a second debit. GET transfers/history/balance do not use this budget. Sandbox
top-ups keep separate access checks; these rules apply to the three stated POST routes.

Exhaustion returns 429 with Retry-After; Redis failure returns safe
503 rate_limiter_unavailable without invoking the use case. Both use
Cache-Control: no-store. Frequency limits do not replace monetary amount limits.
HTTP contracts and RU/EN documentation describe these errors.

Tests: tests/integration/api/test_rate_limits.py covers both refusal paths, settings,
normalization and authentication; tests/integration/test_redis_auth_limits.py checks
real shared budgets across changes of IP/case/Idempotency-Key. PostgreSQL tests also
verify that 429/503 create no financial operations and permitted replay returns
the original transfer_id without another debit.

Production needs HTTPS for API and both `FRONTEND_*_URL` values and trusted proxy
IPs in Uvicorn. Do not record auth request/response bodies in Nginx/APM/analytics.
Reset pages must exclude third-party scripts and persistent password storage.
The frontend reset page connects to these routes through the Next.js gateway.

RU/EN ReDoc covers both reset endpoints and `change-password`. End-to-end pytest
`tests/integration/persistence/test_password_reset.py` checks PostgreSQL,
SMTP/Mailpit, new-password login, rejection of old password/refresh, outbox cleanup,
concurrent reset and full rollback on notification failure. SMTP uses the same
`FINCORE_TEST_SMTP_PORT` and `FINCORE_TEST_MAILPIT_URL` as registration tests.

### Profile and session management

The user router is mounted at `/v1/users`. All four routes require
`Authorization: Bearer <access_token>` and derive user_id from the verified JWT:

| Method | Path                                 | Response                                        |
| ------ | ------------------------------------ | ----------------------------------------------- |
| GET    | `/v1/users/me`                       | `200`, profile: id, username, email, created_at |
| GET    | `/v1/users/me/sessions`              | `200`, active sessions array or `[]`            |
| DELETE | `/v1/users/me/sessions`              | `204`, revoke all owned sessions                |
| DELETE | `/v1/users/me/sessions/{session_id}` | `204`, revoke one owned session                 |

Sessions are ordered by created_at DESC, id DESC. Revoked/expired records are
excluded, including expires_at == now. Responses contain original IP/User-Agent
and latest refresh metadata, never password hashes or tokens. Username/Email become
strings at the HTTP boundary. Profile/session responses, including expected errors,
use `Cache-Control: no-store`.

Repeatedly revoking an owned session is safe. Missing/foreign sessions share
`404 session_not_found`. Invalid UUID → `422`; missing/invalid JWT → `401`;
inactive user → `403`. Both DELETE responses have no body. Revocation stops refresh;
issued access JWTs last until expiry. `last_used_at` updates on refresh, not every request.

### Creating, renaming and closing wallets

Wallet router uses `/v1/wallets`, following auth/user router style. Every operation
requires Bearer access JWT and an existing active user:

| Method | Path                            | Body                               | Success                   |
| ------ | ------------------------------- | ---------------------------------- | ------------------------- |
| POST   | `/v1/wallets`                   | `{"name":"Main","currency":"USD"}` | `201 {"wallet_id":"..."}` |
| PATCH  | `/v1/wallets/{wallet_id}`       | `{"name":"Savings"}`               | `204`, no body            |
| POST   | `/v1/wallets/{wallet_id}/close` | No body                            | `204`, no body            |

Default currency is USD, matching CreateWalletCommand. Trimmed names contain
1–64 characters. Create/rename reject extra fields; user_id comes from JWT and
RandomWalletNumberGenerator creates the number. Creation atomically saves the
wallet, zero WalletBalance and liability LedgerAccount. Application retries number
collisions with rollback between attempts; exhaustion yields
`503 wallet_number_unavailable`.

Foreign/missing wallets share `404 wallet_not_found`. A closed wallet cannot be
renamed (`409 wallet_closed`). Nonzero balances prohibit closure
(`409 wallet_balance_not_zero`); zero-balance closure closes wallet/account while
retaining balance/history. Repeated closure succeeds. Inconsistent accounting
state returns controlled `500 wallet_accounting_state_error` without internal details.

Creation is not idempotent: another POST creates another wallet. Responses use
`Cache-Control: no-store`. GET /v1/wallets and GET /v1/wallets/{wallet_id} are connected
to application queries; history routes are listed below. RU/EN ReDoc documents
them. Dependencies/schemas live in `presentation/api/v1/dependencies/wallet.py`
and `presentation/api/v1/schemas/wallet.py`.

### Reading wallets

`GET /v1/wallets` returns owned wallets with balances;
`GET /v1/wallets/{wallet_id}` returns one owned wallet. Bearer access JWT is required.
Authorization supplies user identity; user_id query parameters cannot select
another owner. The query checks that the user exists and is active.

List parameters:

- `currency=CAD` — currency filter.
- `status=active` — active, frozen or closed; omitted means all statuses.
- `sort_by=balance:desc` — name/currency/balance/created_at/status with asc/desc.
  Default created_at:asc, tie-breaker id ASC.

Example: `/v1/wallets?currency=CAD&status=active&sort_by=balance:desc`.
No matches returns `200 []`. The full filtered list is returned; pagination is not
yet implemented. Balance sorting compares integer minor units without FX conversion.

Response fields: id, user_id, name, balance_minor, number, currency, status,
created_at and updated_at. Number remains a 20-digit string, preserving leading
zeroes; balance_minor is a decimal string of integer minor units. updated_at is
wallet metadata time, not balance modification time.

The reader issues one SELECT with LEFT JOIN wallet_balances; the query also reads
the user. Single-get ownership is constrained in SQL before DTO conversion.
Missing/foreign wallets share `404 wallet_not_found`. An owned wallet missing a
balance returns controlled `500 wallet_accounting_state_error`, never zero or
silent omission. Reads take no row locks and do not commit. Responses use
`Cache-Control: no-store`.

### Transfers, history and balances

Financial use cases and queries connect to SQLAlchemy UoW and HTTP:

| Method | Path                                   | Handler                      |
| ------ | -------------------------------------- | ---------------------------- |
| POST   | `/v1/transfers`                        | `CreateTransferUseCase`      |
| GET    | `/v1/transfers`                        | `GetMyTransfersQuery`        |
| GET    | `/v1/transfers/{transfer_id}`          | `GetTransferQuery`           |
| POST   | `/v1/sandbox/top-ups`                  | `CreateSandboxTopUpUseCase`  |
| GET    | `/v1/wallets/{wallet_id}/transactions` | `GetWalletTransactionsQuery` |
| GET    | `/v1/users/me/transactions`            | `GetMyTransactionsQuery`     |
| GET    | `/v1/wallets/{wallet_id}/balance`      | `GetWalletBalanceQuery`      |
| GET    | `/v1/users/me/balances`                | `GetMyBalanceSummaryQuery`   |

Every route requires Bearer access JWT, returns `Cache-Control: no-store` and is
documented in RU/EN OpenAPI/ReDoc. Actor comes from JWT. Detail routes give the
same 404 for foreign and missing transfers/wallets.

Both commands require `Idempotency-Key`: 1..255 ASCII characters without whitespace.
The same actor/scope/key and payload returns the original ID (201); another payload
gives 409. Waiting for a busy key is bounded to two seconds, then returns
409 idempotency_in_progress; retry the same key/payload. Replay is retained for at
least 24 hours. Maintenance defaults to archiving full records after seven days
while preserving compact permanent receipts for late retries. A new key means a
new operation. Refusals/exceptions roll back the entire attempt, including claim;
REJECTED is not currently persisted.

Transfer accepts sender_wallet_id, receiver_wallet_id, amount_minor and currency.
Sandbox accepts wallet_id, amount_minor and currency. Input amount_minor is a
positive integer or decimal string within signed BIGINT; bool/float are rejected.
Results are transfer_id and top_up_id respectively. New responses return minor
amounts and version as **strings** to preserve large-number precision in JavaScript.
`WalletResponse.balance_minor` is also a string; UI uses BigInt.

Transfer/history lists return `{items, next_cursor}`, default limit=20, maximum 100.
Transfers sort created_at/id DESC; history sorts posted_at/id DESC. Signed cursors
bind actor, list type and filters. PAGINATION_SECRET_KEY is optional: otherwise DI
derives a separate HMAC key from JWT_SECRET_KEY. Every API instance needs the same
key; rotation invalidates old cursors. Filter dates require timezones and use
[from, to). Full filters/examples are in ReDoc.

History shows only posted journals and lists an internal transfer once. Selecting
a wallet makes direction relative to it. Frozen/closed balances remain readable;
their spendable is 0. Summary computes separate currency totals in one statement;
available=posted until holds exist. A missing owned projection is a 500 integrity error.

Apply migrations:

```bash
poetry run alembic upgrade head
```

Migration 20261112_04 creates transfers, sandbox_top_ups, ledger_transactions,
ledger_entries, idempotency_records, sandbox_operators and supported-currency
funding accounts. PostgreSQL enforces relationships/currencies, unique journals,
entry/source agreement and balanced pairs; posted records are immutable.
Balance projections change with the journal in one UoW transaction. Read-only
reconciliation is a separate query/CLI; database role separation remains operational work.

Sandbox is disabled by default (`SANDBOX_ENABLED=false`). Local funding requires
both the enabled flag and server-managed permission for an active operator:

```bash
poetry run python -m backend.bootstrap.sandbox --operator-user-id <USER_UUID>
poetry run python -m backend.bootstrap.sandbox --operator-user-id <USER_UUID> --revoke
```

CLI grants/revokes permission without changing SANDBOX_ENABLED; HTTP body roles
are not accepted. `TRANSFER_MAX_AMOUNT_MINOR` and `SANDBOX_MAX_AMOUNT_MINOR` limit
a single new operation; defaults are the signed BIGINT technical limit. Product
daily/aggregate limits are not implemented.

`tests/integration/persistence/test_finance_endpoints.py` uses a separate test
PostgreSQL and covers all eight routes, ACL, filters/cursors, competing transfers/
keys, overspending, full rollback, large amounts, permission grants/revocations
and journal protection. `test_repositories.py` checks migration upgrade/downgrade
and schema/model agreement.

### VPS Docker, health and logs

Frontend connects through the Next.js server gateway; startup, Mailpit and sandbox
permission instructions are in [frontend/README.md](../frontend/README.md).
`WalletResponse.balance_minor` is a decimal JSON string like other finance amounts,
preserving 64-bit precision in JavaScript.

`backend/Dockerfile`, `frontend/Dockerfile` and root `compose.yml` run Next.js, API,
outbox worker, maintenance, PostgreSQL, Redis and a separate migration job. Settings
come from root .env, not backend/.env. Follow [deployment](../docs/deployment.md)
for startup/updates. Only frontend is published on loopback (default 3000); API,
PostgreSQL and Redis stay inside Docker networks. The gateway validates ingress
secret and a single Nginx IP; Uvicorn trusts only the dedicated frontend address.
Nginx and backups are not provisioned here.

`/health` and `/health/live` need no external services. `/health/ready` concurrently
checks PostgreSQL SELECT 1 and Redis PING with HEALTH_CHECK_TIMEOUT (default
2 seconds, maximum 10), returning 200 or safe 503. SMTP/SES is not checked.
Middleware returns X-Request-ID and logs JSON metadata: route template, status,
duration_ms and request_id. Bodies, tokens and raw URLs are neither read nor logged.
The Docker launcher disables Uvicorn access logs; the worker shares the formatter.
Logs go to stdout; Docker retains three 10 MB files per container. External metrics
and dashboards are not installed.

FreezeWalletUseCase/UnfreezeWalletUseCase use POST
`/v1/wallets/{wallet_id}/freeze` and `/unfreeze`. Only an active owner is allowed;
204 is idempotent; CLOSED returns 409. Status is checked under shared locks;
balance/account do not change. Frozen wallets prohibit new movements but keep
history and balances readable.

Operational reconciliation: `python -m backend.bootstrap.reconcile_ledger --sample-limit 10`.
[Reconciliation README](src/backend/application/reconciliation/README.md) explains
checks, the single snapshot, bounded samples and exit codes 0/1/2.
There is no automatic data repair.

### Transfer recipient lookup

`POST /v1/transfer-recipients/resolve` accepts `wallet_number`, exactly 20 ASCII
digits. `ResolveWalletRecipientQuery` checks the current user's activity and calls
`IWalletReader.get_recipient_by_number()` to retrieve `wallet_id`, `number`,
`currency` and `owner`. `owner` is the recipient wallet owner's username. SQL
uses the unique number and JOIN users; balances, email and private wallet names
are excluded.

Lookup requires the complete number of an active wallet with an active owner.
Unknown, frozen, closed wallets and inactive owners share 404 wallet_not_found.
Owned wallets can also be resolved. The query uses no locks/commit; creating a
transfer rechecks wallet state, currency, access and balance. Successful lookup
does not guarantee continued activity at confirmation time.

Redis limits: RECIPIENT_LOOKUP_RATE_LIMIT_USER_PER_MINUTE=30 and
RECIPIENT_LOOKUP_RATE_LIMIT_IP_PER_MINUTE=100. An unavailable limiter returns 503
before reading. Number is in the body; responses use no-store. RU/EN OpenAPI
includes schema/examples. Frontend shows recipient username/currency, clears the
result when the number changes and uses UUID inside the existing transfer request.
Wallet details can copy the complete number.

### Resending confirmation

`POST /v1/auth/confirm/resend` accepts only `email`, without JWT. Valid admitted
requests return identical `202` for unknown, active and pending accounts. Only
`pending_confirmation` gets a new challenge: under the user lock, old unused
registration links are invalidated, and the new hash/outbox are saved atomically.
Password-reset challenges are unchanged. Confirm uses the same user → challenge
lock order.

The link lifetime is `VERIFICATION_CONFIRMATION_TTL`. Redis counts all attempts:
`RESEND_CONFIRMATION_RATE_LIMIT_IP_PER_HOUR=20` and
`RESEND_CONFIRMATION_RATE_LIMIT_EMAIL_PER_HOUR=3`. Exhaustion returns `429` with
Retry-After; unavailable limiter returns `503` before the use case. Delivery needs
the worker; `202` does not guarantee it. Frontend offers resend from login,
registration and confirmation. RU/EN OpenAPI/ReDoc provides contract, errors and examples.

### Cleanup and CI

`make cleanup-preview` shows candidates; `make cleanup` executes one pass.
Compose `maintenance` runs immediately and then daily. It cleans expired/revoked
sessions with refresh chains, old challenges and terminal outbox, and archives
full idempotency records. Active data and financial records remain. Policy,
batch limits, reports and rollback restrictions are described in
[maintenance](../docs/maintenance.md).

Migration `20261115_06` adds cleanup indexes and `idempotency_receipts`.
Permanent receipts preserve the original result and payload hash under SHA-256
actor/scope/key identity; they have no TTL cleanup. A late retry returns the same
result; a different payload gives `409`. The DB prohibits deleting a full replay
without a receipt and modifying receipts. Downgrade is prohibited after the first archive.

[GitHub Actions](../.github/workflows/ci.yml) checks the complete backend on Python
3.13/3.14 with PostgreSQL, Redis and Mailpit, zero skips and a 91% coverage gate.
Separate jobs check frontend, browser E2E and the full production Docker stack.
`CI required checks` requires every job to succeed; reports are retained for 14 days.
The [CI guide](../docs/ci.md) describes environment/artifacts. An actual Actions
run follows push; local results are in the
[17 November report](../docs/test-report-2026-11-17.md).

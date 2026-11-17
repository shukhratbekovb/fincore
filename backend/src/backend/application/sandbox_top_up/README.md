# CreateSandboxTopUpUseCase

Application-сценарий пополнения виртуальных средств оператором sandbox.
`CreateSandboxTopUpCommand.user_id` поступает из доверенного server context,
`idempotency_key` — из Idempotency-Key. Команда не содержит флага роли.
Результат — `CreateSandboxTopUpResult(top_up_id=...)`.

Конструктор принимает UoW, clock, `sandbox_enabled` (по умолчанию False) и
`max_amount_minor` (по умолчанию технический предел signed BIGINT). При HTTP
wiring флаг и бизнес-лимит поступают из SANDBOX_ENABLED и SANDBOX_MAX_AMOUNT_MINOR.
Дневные/суммарные лимиты и rate limiting пока не реализованы.

## Проверки и доступ

- Валидные UUID, положительная целая сумма в пределах BIGINT, CurrencyEnum,
  непустой ASCII key без пробелов, до 255 символов.
- Actor существует, ACTIVE и имеет server-managed право оператора.
  Владение кошельком само по себе этого права не предоставляет.
- Право читается через `uow.sandbox_operator_reader.is_operator(...)` до replay
  и повторно под блокировкой actor для новой операции. Grant/revoke должны
  сериализуются на той же user-строке через SQL adapter и DB trigger.
- Целевой wallet существует, ACTIVE и имеет валюту команды. Оператор может
  пополнить кошелёк другого пользователя. Статус владельца целевого кошелька
  отдельно не проверяется, как и в текущем CreateTransferUseCase.
- WalletBalance и LIABILITY account существуют и относятся к этому wallet;
  account активен, валюта совпадает.
- Есть заранее созданный активный системный ASSET account без wallet_id,
  с кодом `SYS:SIM_FUNDING:{currency}`. Он не создаётся автоматически при posting.
- Credit проекции не переполняет баланс или version.

## Выполнение

1. Проверить команду, активность и полномочия actor.
2. Claim `(user_id, sandbox_top_up.create, key)` в общей UoW-транзакции.
   Hash содержит wallet_id, amount_minor и currency. Replay возвращает прежний
   top_up_id; другой payload — конфликт; незавершённый claim — in-progress.
3. Для новой операции заблокировать actor и перепроверить статус и право.
   Проверить sandbox_enabled и бизнес-лимит.
4. Блокировки: actor → wallet → balance → wallet account → system funding account.
   Funding блокируется после wallet accounts; последующих финансовых locks нет.
   Это продолжает порядок wallet → balance → account существующих команд.
5. После locks получить один now. Создать SandboxTopUp с actor в
   initiated_by_user_id, увеличить проверенную копию WalletBalance, вызвать complete.
6. `LedgerTransaction.for_sandbox_top_up` создаёт DEBIT системного ASSET account
   и CREDIT пользовательского LIABILITY account. Ровно две записи, один journal.
   Отдельного WalletBalance у системного funding account в текущей модели нет.
7. Сохранить top-up, весь journal, новую проекцию и replay result, один commit.

Авторизованный replay остаётся доступен после выключения sandbox или снижения
лимита: он не создаёт новое движение. Неактивный actor или actor с отозванным
правом результат не получает. Новый key означает новое намерение пополнения.
Если результат handler расширится за пределы одного ID, replay snapshot также
потребуется расширить.

Отказы и технические исключения выходят через UoW с rollback всей попытки,
включая claim. REJECTED не сохраняется, автоматических retries нет.

## Готовность

Реализованы handler, SQL adapters, settings, dependencies, UoW и
POST /v1/sandbox/top-ups. Миграция 20261112_04 создаёт funding accounts всех
поддерживаемых валют. Sandbox выключен по умолчанию; включение флага не выдаёт роль.
Разрешение выдаётся через python -m backend.bootstrap.sandbox --operator-user-id UUID;
тот же вызов с --revoke отзывает разрешение. HTTP не принимает роль от клиента.
PostgreSQL-тесты проверяют доступ, replay, rollback и journal constraints.
Разделение DB roles/privileges и reconciliation остаются отдельными задачами.

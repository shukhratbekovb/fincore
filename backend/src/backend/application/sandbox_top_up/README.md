# CreateSandboxTopUpUseCase

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

Application-сценарий пополнения виртуальных средств оператором sandbox.
`CreateSandboxTopUpCommand.user_id` поступает из доверенного server context,
`idempotency_key` — из Idempotency-Key. Команда не содержит флага роли.
Результат — `CreateSandboxTopUpResult(top_up_id=...)`.

Конструктор принимает UoW, clock, `sandbox_enabled` (по умолчанию False) и
`max_amount_minor` (по умолчанию технический предел signed BIGINT). При HTTP
wiring флаг и бизнес-лимит поступают из SANDBOX_ENABLED и SANDBOX_MAX_AMOUNT_MINOR.
Дневные/суммарные лимиты и rate limiting пока не реализованы.

### Проверки и доступ

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

### Выполнение

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

### Готовность

Реализованы handler, SQL adapters, settings, dependencies, UoW и
POST /v1/sandbox/top-ups. Миграция 20261112_04 создаёт funding accounts всех
поддерживаемых валют. Sandbox выключен по умолчанию; включение флага не выдаёт роль.
Разрешение выдаётся через python -m backend.bootstrap.sandbox --operator-user-id UUID;
тот же вызов с --revoke отзывает разрешение. HTTP не принимает роль от клиента.
PostgreSQL-тесты проверяют доступ, replay, rollback и journal constraints.
Reconciliation реализована отдельной query и CLI; разделение DB roles/privileges
остаётся эксплуатационной задачей.

<a id="en"></a>

## English

Application workflow for an authorized sandbox operator to add virtual funds.
`CreateSandboxTopUpCommand.user_id` comes from trusted server context;
`idempotency_key` comes from Idempotency-Key. The command contains no role flag.
The result is `CreateSandboxTopUpResult(top_up_id=...)`.

The constructor accepts a UoW, clock, `sandbox_enabled` (default False), and
`max_amount_minor` (default the technical signed BIGINT limit). HTTP wiring reads
the flag and business limit from SANDBOX_ENABLED and SANDBOX_MAX_AMOUNT_MINOR.
Daily/aggregate limits and top-up rate limiting are not implemented yet.

### Validation and access

- Valid UUIDs, a positive integer amount within BIGINT, CurrencyEnum,
  and a nonempty ASCII key without whitespace, up to 255 characters.
- The actor exists, is ACTIVE and has server-managed operator permission.
  Owning a wallet does not grant that permission.
- Permission is read through `uow.sandbox_operator_reader.is_operator(...)` before
  replay and rechecked under the actor lock for a new operation. Grants/revocations
  must serialize on that same user row through the SQL adapter and DB trigger.
- The target wallet exists, is ACTIVE and matches the command currency. An operator
  may fund another user's wallet. The target owner's status is not separately
  checked, matching the current CreateTransferUseCase.
- WalletBalance and the LIABILITY account exist and belong to this wallet;
  the account is active and its currency matches.
- An active system ASSET account without wallet_id already exists, with code
  `SYS:SIM_FUNDING:{currency}`. Posting does not create it automatically.
- Crediting the projection does not overflow the balance or version.

### Execution

1. Validate the command and the actor's activity and permission.
2. Claim `(user_id, sandbox_top_up.create, key)` in the shared UoW transaction.
   The hash includes wallet_id, amount_minor and currency. Replay returns the
   original top_up_id; a different payload conflicts; an unfinished claim is in progress.
3. For a new operation, lock the actor and recheck status and permission.
   Check sandbox_enabled and the business limit.
4. Lock order: actor → wallet → balance → wallet account → system funding account.
   Funding is locked after wallet accounts, with no later financial locks.
   This extends the existing wallet → balance → account command order.
5. After locking, obtain one now. Create SandboxTopUp with the actor in
   initiated_by_user_id, credit a validated WalletBalance copy, then call complete.
6. `LedgerTransaction.for_sandbox_top_up` creates a DEBIT to the system ASSET
   account and a CREDIT to the user's LIABILITY account: exactly two entries,
   one journal. The system funding account has no separate WalletBalance.
7. Save the top-up, entire journal, updated projection and replay result; commit once.

Authorized replay remains available after sandbox is disabled or its limit is
reduced: it creates no new movement. Inactive actors or actors whose permission
was revoked cannot retrieve the result. A new key means a new funding intent.
Expand the replay snapshot if the handler result expands beyond one ID.

Refusals and infrastructure exceptions leave the UoW with rollback of the whole
attempt, including the claim. REJECTED is not persisted; there are no automatic retries.

### Implementation status

The handler, SQL adapters, settings, dependencies, UoW and POST /v1/sandbox/top-ups
are implemented. Migration 20261112_04 creates funding accounts for all supported
currencies. Sandbox is disabled by default; enabling the flag grants no role.
Grant permission with `python -m backend.bootstrap.sandbox --operator-user-id UUID`;
add `--revoke` to revoke it. HTTP does not accept a client-supplied role.
PostgreSQL tests cover access, replay, rollback and journal constraints.
Reconciliation is implemented as a separate query and CLI; DB role/privilege
separation remains an operational task.

"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ArrowDown,
  ArrowDownUp,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCheck,
  ChevronRight,
  ShieldCheck,
  UserRound,
  Wallet,
} from "lucide-react";
import { z } from "zod";
import {
  currencies,
  inputMoney,
  money,
  parseMoney,
  transactionLabel,
  type Command,
  type Transaction,
} from "@/lib/data";
import { api, ApiError } from "@/lib/api";
import { clearPending, readPending, savePending } from "@/lib/pending";
import { useFinCore } from "./provider";
import { useWalletRecipient } from "@/lib/use-wallet-recipient";
import { EmptyState, PageHeading } from "./ui";

const transferSchema = z
  .object({
    id: z.string().uuid(),
    sender_wallet_id: z.string(),
    receiver_wallet_id: z.string(),
    amount_minor: z.string().regex(/^\d+$/),
    currency: z.enum(currencies),
    status: z.enum(["pending", "completed", "rejected"]),
    direction: z.enum(["incoming", "outgoing", "internal"]),
    created_at: z.string(),
    completed_at: z.string().nullable(),
    rejection_code: z.string().nullable(),
  })
  .transform((t) => ({
    id: t.id,
    journalId: "",
    source: t.sender_wallet_id,
    destination: t.receiver_wallet_id,
    amount: BigInt(t.amount_minor),
    currency: t.currency,
    kind: t.direction,
    date: t.completed_at || t.created_at,
    status: t.status,
    rejection: t.rejection_code,
  }));
function uncertain(failure: unknown) {
  return (
    !(failure instanceof ApiError) ||
    failure.status === 0 ||
    failure.status >= 500 ||
    failure.code === "idempotency_in_progress"
  );
}

export function TransferForm() {
  const { state, user, reload } = useFinCore();
  const params = useSearchParams();
  const active = state.wallets.filter((w) => w.status === "active");
  const [mode, setMode] = useState<"internal" | "external">("internal");
  const [source, setSource] = useState(active[0]?.id || "");
  const [destination, setDestination] = useState("");
  const [external, setExternal] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [command, setCommand] = useState<Command | null>(null);
  const [result, setResult] = useState<Transaction | null>(null);
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const sending = useRef(false);
  const resultRef = useRef<HTMLHeadingElement>(null);
  const lookup = useWalletRecipient(
    external,
    mode === "external" && !command && !result,
  );
  const storageKey = `fincore.transfer.v1.${user?.id}`;
  useEffect(() => {
    const pending = readPending(storageKey);
    if (pending) {
      setCommand(pending);
      setSource(pending.source);
      setLocked(true);
    }
  }, [storageKey]);
  useEffect(() => {
    const selected = params.get("source");
    if (selected && state.wallets.some((w) => w.id === selected))
      setSource(selected);
  }, [params, state.wallets]);
  useEffect(() => {
    if (result) resultRef.current?.focus();
  }, [result]);
  const sender = state.wallets.find(
    (w) => w.id === (command?.source || source),
  );
  const receiver = state.wallets.find(
    (w) => w.id === (command?.destination || destination),
  );
  const name = (id: string) =>
    state.wallets.find((w) => w.id === id)?.name ||
    (command?.recipient?.wallet_id === id
      ? command.recipient.owner
      : "Кошелёк пользователя");
  if (result)
    return (
      <div className="transfer-layout">
        <section className="panel success-panel">
          <span className="success-icon">
            <CheckCheck size={34} />
          </span>
          <span className="eyebrow">ГОТОВО</span>
          <h1 ref={resultRef} tabIndex={-1}>
            Перевод выполнен
          </h1>
          <div className="success-amount">
            {money(result.amount, result.currency)}{" "}
            <small>{result.currency}</small>
          </div>
          <p>Баланс обновлён. Операция сохранена на сервере.</p>
          <div className="review-summary">
            <div>
              <span>Откуда</span>
              <strong>{name(result.source!)}</strong>
            </div>
            <div>
              <span>Куда</span>
              <strong>{name(result.destination)}</strong>
            </div>
          </div>
          <Link
            className="button primary full"
            href={`/transfers/${result.id}`}
          >
            Детали операции <ChevronRight size={17} />
          </Link>
          <button
            className="button ghost full"
            onClick={() => {
              setResult(null);
              setCommand(null);
              setAmount("");
              setError("");
              setLocked(false);
            }}
          >
            Ещё один перевод
          </button>
        </section>
      </div>
    );
  if (!sender && !command)
    return (
      <EmptyState
        title="Нет активных кошельков"
        text="Создайте кошелёк в разделе «Кошельки» или разморозьте существующий."
      />
    );
  const currency = command?.currency || sender!.currency;
  return (
    <>
      <PageHeading
        eyebrow="ПРОСТО. БЫСТРО. ПОНЯТНО."
        title="Перевод средств"
        subtitle="Между своими кошельками или другому пользователю."
      />
      <div className="transfer-layout">
        <section className="panel transfer-panel">
          {command ? (
            <>
              {!locked && (
                <button
                  className="back-link"
                  disabled={busy}
                  onClick={() => {
                    clearPending(storageKey);
                    setCommand(null);
                    setError("");
                  }}
                >
                  <ArrowLeft size={16} /> Изменить данные
                </button>
              )}
              <h2>Всё верно?</h2>
              <p className="muted">
                Проверьте кошельки и сумму перед подтверждением.
              </p>
              <div className="review-amount">
                {money(command.amount, command.currency)}{" "}
                <small>{command.currency}</small>
              </div>
              <div className="review-summary">
                <div>
                  <span>Откуда</span>
                  <strong>{name(command.source)}</strong>
                </div>
                <div>
                  <span>Куда</span>
                  <strong>{name(command.destination)}</strong>
                </div>
                <div className="review-id">
                  <span>Номер кошелька получателя</span>
                  <code>
                    {command.recipient?.number ||
                      receiver?.number ||
                      "Номер недоступен"}
                  </code>
                </div>
              </div>
              {error && (
                <p className="error-message" role="alert">
                  {error}
                </p>
              )}
              <button
                className="button primary full"
                disabled={busy}
                onClick={async () => {
                  if (sending.current) return;
                  sending.current = true;
                  setBusy(true);
                  setError("");
                  try {
                    savePending(storageKey, command);
                    setLocked(true);
                    const response = await api<{ transfer_id: string }>(
                      "transfers",
                      {
                        method: "POST",
                        key: command.key,
                        body: {
                          sender_wallet_id: command.source,
                          receiver_wallet_id: command.destination,
                          amount_minor: command.amount.toString(),
                          currency: command.currency,
                        },
                      },
                    );
                    const completed = transferSchema.parse(
                      await api(`transfers/${response.transfer_id}`),
                    );
                    if (completed.status !== "completed")
                      throw new Error(
                        "Перевод ещё не завершён. Повторите проверку с тем же ключом.",
                      );
                    clearPending(storageKey);
                    setResult(completed);
                    await reload().catch(() => {});
                  } catch (failure) {
                    setLocked(uncertain(failure));
                    setError(
                      failure instanceof Error
                        ? failure.message
                        : "Не удалось выполнить перевод.",
                    );
                  } finally {
                    sending.current = false;
                    setBusy(false);
                  }
                }}
              >
                {busy ? "Выполняем…" : "Подтвердить перевод"}{" "}
                <ArrowRight size={18} />
              </button>
              <p className="form-footnote">
                {locked
                  ? "Если ответ потерялся, повторите подтверждение. Сохранённый ключ защищает от повторного списания, в том числе после перезагрузки."
                  : "Баланс и лимиты проверит сервер. Все средства виртуальные."}
              </p>
            </>
          ) : (
            <>
              <div
                className="segmented"
                role="group"
                aria-label="Сценарий перевода"
              >
                <button
                  aria-pressed={mode === "internal"}
                  className={mode === "internal" ? "active" : ""}
                  onClick={() => {
                    setMode("internal");
                    setError("");
                  }}
                >
                  <ArrowDownUp size={17} /> Между своими
                </button>
                <button
                  aria-pressed={mode === "external"}
                  className={mode === "external" ? "active" : ""}
                  onClick={() => {
                    setMode("external");
                    setError("");
                  }}
                >
                  <UserRound size={17} /> Пользователю
                </button>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  try {
                    const minor = parseMoney(amount, currency);
                    const recipient =
                      mode === "internal" && receiver
                        ? {
                            wallet_id: receiver.id,
                            number: receiver.number,
                            currency: receiver.currency,
                            owner: user!.username,
                          }
                        : lookup.recipient;
                    if (
                      !recipient ||
                      (mode === "external" && recipient.number !== external)
                    )
                      throw new Error(
                        "Дождитесь поиска получателя по номеру кошелька.",
                      );
                    if (recipient.currency !== currency)
                      throw new Error(
                        "Валюты кошельков отправителя и получателя должны совпадать.",
                      );
                    const target = recipient.wallet_id;
                    if (source === target)
                      throw new Error("Выберите другой кошелёк получателя.");
                    if (minor > sender!.balance)
                      throw new Error(
                        "Недостаточно средств на выбранном кошельке.",
                      );
                    const next = {
                      key: crypto.randomUUID(),
                      source,
                      destination: target,
                      amount: minor,
                      currency,
                      recipient,
                    };
                    savePending(storageKey, next);
                    setCommand(next);
                    setError("");
                  } catch (failure) {
                    setError(
                      failure instanceof Error
                        ? failure.message
                        : "Проверьте данные.",
                    );
                  }
                }}
              >
                <label className="field">
                  Откуда
                  <div className={`wallet-select ${sender!.color}`}>
                    <Wallet size={22} />
                    <select
                      aria-label="Кошелёк списания"
                      value={source}
                      onChange={(e) => {
                        setSource(e.target.value);
                        setDestination("");
                        setAmount("");
                      }}
                    >
                      {active.map((w) => (
                        <option key={w.id} value={w.id}>
                          {w.name} · {money(w.balance, w.currency)} {w.currency}
                        </option>
                      ))}
                    </select>
                  </div>
                </label>
                <div className="transfer-connector">
                  <ArrowDown size={17} />
                </div>
                {mode === "internal" ? (
                  <label className="field destination-field">
                    Куда
                    <div
                      className={`wallet-select ${receiver?.color || "blue"}`}
                    >
                      <Wallet size={22} />
                      <select
                        required
                        aria-label="Кошелёк получателя"
                        value={destination}
                        onChange={(e) => setDestination(e.target.value)}
                      >
                        <option value="" disabled>
                          Выберите кошелёк
                        </option>
                        {active
                          .filter(
                            (w) => w.id !== source && w.currency === currency,
                          )
                          .map((w) => (
                            <option key={w.id} value={w.id}>
                              {w.name} · {money(w.balance, w.currency)}{" "}
                              {w.currency}
                            </option>
                          ))}
                      </select>
                    </div>
                    <span className="field-hint">
                      Показаны активные кошельки в {currency}.
                    </span>
                  </label>
                ) : (
                  <div className="field destination-field">
                    <label htmlFor="recipient-wallet-number">
                      Номер кошелька получателя
                    </label>
                    <input
                      id="recipient-wallet-number"
                      required
                      value={external}
                      onChange={(e) => {
                        setExternal(e.target.value.replace(/[ -]/g, ""));
                        setError("");
                      }}
                      placeholder="20 цифр"
                      inputMode="numeric"
                      pattern="[0-9]{20}"
                      maxLength={24}
                      autoComplete="off"
                    />
                    <span className="field-hint">
                      Попросите номер у получателя. Валюта его кошелька должна
                      быть {currency}.
                    </span>
                    {lookup.loading && (
                      <span role="status">Ищем получателя…</span>
                    )}
                    {lookup.error && (
                      <div className="error-message" role="alert">
                        {lookup.error}
                        <button
                          className="text-link"
                          type="button"
                          onClick={lookup.retry}
                        >
                          Повторить поиск
                        </button>
                      </div>
                    )}
                    {lookup.recipient && (
                      <div className="recipient-preview" role="status">
                        <strong>Получатель: {lookup.recipient.owner}</strong>
                        <span>
                          {lookup.recipient.number} ·{" "}
                          {lookup.recipient.currency}
                        </span>
                        {lookup.recipient.currency !== currency && (
                          <span className="error-message">
                            Валюта получателя не совпадает с валютой списания.
                          </span>
                        )}
                        {lookup.recipient.wallet_id === source && (
                          <span className="error-message">
                            Выберите другой кошелёк получателя.
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                )}
                <label className="field amount-field">
                  Сумма
                  <div className="amount-input">
                    <input
                      aria-label="Сумма"
                      required
                      inputMode="decimal"
                      placeholder="0,00"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                    />
                    <span>{currency}</span>
                  </div>
                  <span className="field-hint">
                    Баланс: {money(sender!.balance, currency)} {currency}
                    <button
                      type="button"
                      onClick={() =>
                        setAmount(inputMoney(sender!.balance, currency))
                      }
                    >
                      Вся сумма
                    </button>
                  </span>
                </label>
                {error && (
                  <p className="error-message" role="alert">
                    {error}
                  </p>
                )}
                <button
                  className="button primary full"
                  type="submit"
                  disabled={
                    mode === "external" &&
                    (!lookup.recipient ||
                      lookup.loading ||
                      lookup.recipient.currency !== currency ||
                      lookup.recipient.wallet_id === source)
                  }
                >
                  Продолжить <ArrowRight size={18} />
                </button>
              </form>
            </>
          )}
        </section>
        <aside className="transfer-aside">
          <span className="advice-icon">
            <ShieldCheck size={26} />
          </span>
          <h3>
            Каждый перевод
            <br />
            под вашим контролем
          </h3>
          <p>
            Сначала проверьте данные, затем подтвердите операцию. Баланс
            обновится после выполнения.
          </p>
          <div className="advice-divider" />
          {[
            "Только виртуальные средства",
            "История операций на сервере",
            "Защита от повторного списания",
          ].map((text) => (
            <div className="advice-item" key={text}>
              <Check size={16} />
              <span>{text}</span>
            </div>
          ))}
        </aside>
      </div>
    </>
  );
}

export function TransferDetails({ id }: { id: string }) {
  const { state } = useFinCore();
  const [transfer, setTransfer] = useState<z.infer<
    typeof transferSchema
  > | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void api(`transfers/${id}`, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted)
          setTransfer(transferSchema.parse(value));
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Ошибка загрузки.");
      });
    return () => controller.abort();
  }, [id]);
  const name = (walletId: string | null) =>
    state.wallets.find((w) => w.id === walletId)?.name ||
    "Кошелёк пользователя";
  if (error)
    return <EmptyState title="Не удалось загрузить перевод" text={error} />;
  if (!transfer) return <p role="status">Загрузка перевода…</p>;
  const t = transfer;
  return (
    <>
      <Link href="/transactions" className="back-link">
        <ArrowLeft size={16} /> История операций
      </Link>
      <PageHeading
        eyebrow="ДЕТАЛИ ОПЕРАЦИИ"
        title={transactionLabel(t)}
        subtitle="Данные перевода из FinCore API."
      />
      <section className="panel detail-panel">
        <span className="active-badge">
          {
            {
              completed: "Выполнен",
              pending: "В обработке",
              rejected: "Отклонён",
            }[t.status]
          }
        </span>
        <div className="review-amount">
          {money(t.amount, t.currency)} <small>{t.currency}</small>
        </div>
        <div className="review-summary">
          <div>
            <span>Отправитель</span>
            <strong>{name(t.source)}</strong>
          </div>
          <div>
            <span>Получатель</span>
            <strong>{name(t.destination)}</strong>
          </div>
          <div>
            <span>Дата и время</span>
            <strong>{new Date(t.date).toLocaleString("ru-RU")}</strong>
          </div>
          {[
            ["Номер кошелька отправителя", t.source],
            ["Номер кошелька получателя", t.destination],
          ].map(([label, walletId]) => {
            const wallet = state.wallets.find((w) => w.id === walletId);
            return wallet ? (
              <div className="review-id" key={label}>
                <span>{label}</span>
                <code>{wallet.number}</code>
              </div>
            ) : null;
          })}
          <div className="review-id">
            <span>ID операции</span>
            <code>{t.id}</code>
          </div>
          {t.rejection && (
            <div>
              <span>Причина отказа</span>
              <strong>{t.rejection}</strong>
            </div>
          )}
        </div>
        <p className="form-footnote">
          Время отображается в часовом поясе устройства. Все средства
          виртуальные.
        </p>
      </section>
    </>
  );
}

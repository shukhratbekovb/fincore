"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowUpRight,
  Plus,
  Wallet as WalletIcon,
} from "lucide-react";
import { z } from "zod";
import {
  currencies,
  money,
  parseMoney,
  statusLabel,
  transactionSchema,
  walletBalanceSchema,
  type Currency,
  type Page,
  type Transaction,
} from "@/lib/data";
import { api, ApiError } from "@/lib/api";
import {
  clearPending,
  readPending,
  savePending,
  type TopUp,
} from "@/lib/pending";
import { useFinCore } from "./provider";
import {
  CopyButton,
  EmptyState,
  Modal,
  PageHeading,
  TransactionList,
  WalletCard,
} from "./ui";

export function Wallets() {
  const { state, addWallet } = useFinCore();
  const params = useSearchParams();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState<Currency>("CAD");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (params.get("create") === "1") setOpen(true);
  }, [params]);
  const close = () => {
    if (busy) return;
    setOpen(false);
    setError("");
    setName("");
    if (params.has("create")) router.replace("/wallets");
  };
  return (
    <>
      <PageHeading
        eyebrow="ДЛЯ КАЖДОЙ ЦЕЛИ"
        title="Мои кошельки"
        subtitle="Разделяйте повседневные расходы и большие планы."
        action={
          <button className="button primary" onClick={() => setOpen(true)}>
            <Plus size={18} /> Создать кошелёк
          </button>
        }
      />
      <div className="wallet-grid all-wallets">
        {state.wallets.map((w) => (
          <WalletCard key={w.id} wallet={w} />
        ))}
        <button className="new-wallet-card" onClick={() => setOpen(true)}>
          <span>
            <Plus size={26} />
          </span>
          <strong>Новый кошелёк</strong>
          <small>Для следующей цели</small>
        </button>
      </div>
      <div className="tip-panel">
        <WalletIcon size={25} />
        <div>
          <h3>Один аккаунт. Разные планы.</h3>
          <p>
            У каждого кошелька свой баланс и история. Переводы доступны между
            активными кошельками одной валюты.
          </p>
        </div>
      </div>
      {open && (
        <Modal title="Новый кошелёк" onClose={close}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (busy) return;
              setBusy(true);
              setError("");
              try {
                await addWallet(name, currency);
                setOpen(false);
                setName("");
                if (params.has("create")) router.replace("/wallets");
              } catch (e) {
                setError(
                  e instanceof Error
                    ? e.message
                    : "Не удалось создать кошелёк.",
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            <label className="field">
              Название
              <input
                autoFocus
                required
                maxLength={64}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Например, На путешествия"
              />
            </label>
            <label className="field">
              Валюта
              <select
                aria-label="Валюта"
                value={currency}
                onChange={(e) => setCurrency(e.target.value as Currency)}
              >
                {currencies.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            {error && (
              <p className="error-message" role="alert">
                {error}
              </p>
            )}
            <button
              className="button primary full"
              disabled={busy}
              type="submit"
            >
              {busy ? "Создаём…" : "Создать кошелёк"}
              <Plus size={18} />
            </button>
            <p className="form-footnote">
              Начальный баланс — 0 {currency}. Для проверки переводов
              используйте Sandbox-пополнение в кошельке.
            </p>
          </form>
        </Modal>
      )}
    </>
  );
}

export function WalletDetails({ id }: { id: string }) {
  const { state, user, walletAction, reload, notify } = useFinCore();
  const wallet = state.wallets.find((w) => w.id === id);
  const [balance, setBalance] = useState<z.infer<
    typeof walletBalanceSchema
  > | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState(wallet?.name || "");
  const [amount, setAmount] = useState("");
  const [pending, setPending] = useState<TopUp | null>(null);
  const [closing, setClosing] = useState(false);
  const sending = useRef(false);
  const storageKey = `fincore.topup.v1.${user?.id}.${id}`;
  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError("");
      try {
        const [totals, history] = await Promise.all([
          api(`wallets/${id}/balance`, { signal }),
          api<Page<unknown>>(`wallets/${id}/transactions?limit=20`, { signal }),
        ]);
        const nextBalance = walletBalanceSchema.parse(totals);
        const nextTransactions = z
          .array(transactionSchema)
          .parse(history.items);
        if (!signal?.aborted) {
          setBalance(nextBalance);
          setTransactions(nextTransactions);
          setCursor(history.next_cursor);
        }
      } catch (e) {
        if (!signal?.aborted)
          setError(e instanceof Error ? e.message : "Ошибка загрузки.");
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [id],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    setPending(readPending(storageKey, true));
    return () => controller.abort();
  }, [load, storageKey]);
  async function action(kind: "rename" | "close" | "freeze" | "unfreeze") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await walletAction(id, kind, name);
      setClosing(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка операции.");
    } finally {
      setBusy(false);
    }
  }
  if (!wallet)
    return (
      <>
        <Link className="back-link" href="/wallets">
          <ArrowLeft size={16} /> К кошелькам
        </Link>
        <EmptyState
          title="Кошелёк не найден"
          text="Выберите доступный кошелёк из списка."
        />
      </>
    );
  return (
    <>
      <Link className="back-link" href="/wallets">
        <ArrowLeft size={16} /> Все кошельки
      </Link>
      <PageHeading
        eyebrow="ВАШ КОШЕЛЁК"
        title={wallet.name}
        subtitle="Баланс, реквизиты и история операций."
        action={
          wallet.status === "active" && (
            <Link
              className="button primary"
              href={`/transfers/new?source=${id}`}
            >
              Перевести <ArrowUpRight size={18} />
            </Link>
          )
        }
      />
      {error && (
        <p className="error-message" role="alert">
          {error}
          <button className="text-link" onClick={() => void load()}>
            Обновить
          </button>
        </p>
      )}
      <div className="wallet-detail-grid">
        <WalletCard wallet={wallet} />
        <section className="panel wallet-info">
          <div className="section-heading">
            <h2>Реквизиты кошелька</h2>
            <span className="active-badge">{statusLabel(wallet.status)}</span>
          </div>
          <span className="muted">Номер кошелька для получения переводов</span>
          <div className="copy-field">
            <code>{wallet.number}</code>
            <CopyButton value={wallet.number} label="номер кошелька" />
          </div>
          <div className="info-pair">
            <span>Доступно для перевода</span>
            <strong>
              {balance ? money(balance.spendable_minor, wallet.currency) : "…"}{" "}
              {wallet.currency}
            </strong>
          </div>
          <small className="muted">
            Передайте отправителю номер кошелька и валюту.
          </small>
        </section>
      </div>
      {wallet.status !== "closed" && (
        <div className="wallet-detail-grid wallet-tools">
          <section className="panel">
            <h2>Настройки кошелька</h2>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void action("rename");
              }}
            >
              <label className="field">
                Новое название
                <input
                  required
                  maxLength={64}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <button className="button secondary" disabled={busy}>
                Переименовать
              </button>
            </form>
            <div className="modal-actions">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void action(
                    wallet.status === "active" ? "freeze" : "unfreeze",
                  )
                }
              >
                {wallet.status === "active" ? "Заморозить" : "Разморозить"}
              </button>
              <button
                className="button ghost"
                disabled={busy || wallet.balance !== 0n}
                onClick={() => setClosing(true)}
              >
                Закрыть кошелёк
              </button>
            </div>
            <p className="form-footnote">
              Закрытие доступно при нулевом балансе. Заморозка блокирует новые
              переводы и пополнения.
            </p>
          </section>
          <section className="panel">
            <h2>Sandbox-пополнение</h2>
            <p className="muted">
              Только виртуальные средства. Требуется право sandbox-оператора.
            </p>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (sending.current) return;
                sending.current = true;
                setBusy(true);
                setError("");
                try {
                  const command = pending || {
                    key: crypto.randomUUID(),
                    amount: parseMoney(amount, wallet.currency),
                    currency: wallet.currency,
                  };
                  savePending(storageKey, command);
                  setPending(command);
                  await api("sandbox/top-ups", {
                    method: "POST",
                    key: command.key,
                    body: {
                      wallet_id: id,
                      amount_minor: command.amount.toString(),
                      currency: command.currency,
                    },
                  });
                  clearPending(storageKey);
                  setPending(null);
                  setAmount("");
                  notify("Кошелёк пополнен");
                  await Promise.all([reload().catch(() => {}), load()]);
                } catch (e) {
                  if (
                    e instanceof ApiError &&
                    [400, 403, 404, 422].includes(e.status)
                  ) {
                    clearPending(storageKey);
                    setPending(null);
                  }
                  setError(
                    e instanceof Error ? e.message : "Ошибка пополнения.",
                  );
                } finally {
                  sending.current = false;
                  setBusy(false);
                }
              }}
            >
              <label className="field">
                Сумма пополнения ({wallet.currency})
                <input
                  inputMode="decimal"
                  required={!pending}
                  disabled={
                    Boolean(pending) || busy || wallet.status !== "active"
                  }
                  value={
                    pending ? money(pending.amount, pending.currency) : amount
                  }
                  onChange={(e) => setAmount(e.target.value)}
                />
              </label>
              <button
                className="button primary"
                disabled={busy || wallet.status !== "active"}
              >
                {busy
                  ? "Пополняем…"
                  : pending
                    ? "Повторить пополнение"
                    : "Пополнить"}
              </button>
              {pending && (
                <p className="form-footnote">
                  Повтор использует сохранённый ключ и ту же сумму: повторного
                  зачисления не будет.
                </p>
              )}
            </form>
          </section>
        </div>
      )}
      <section className="panel history-panel">
        <div className="section-heading">
          <h2>Операции кошелька</h2>
        </div>
        {loading ? (
          <p role="status">Загрузка…</p>
        ) : (
          <TransactionList transactions={transactions} walletId={id} />
        )}
        {cursor && (
          <button
            className="button secondary"
            disabled={loading}
            onClick={async () => {
              setLoading(true);
              try {
                const page = await api<Page<unknown>>(
                  `wallets/${id}/transactions?limit=20&cursor=${encodeURIComponent(cursor)}`,
                );
                setTransactions((old) => [
                  ...old,
                  ...z.array(transactionSchema).parse(page.items),
                ]);
                setCursor(page.next_cursor);
              } catch (e) {
                setError(e instanceof Error ? e.message : "Ошибка истории.");
              } finally {
                setLoading(false);
              }
            }}
          >
            Показать ещё
          </button>
        )}
      </section>
      {closing && (
        <Modal
          title="Закрыть кошелёк?"
          onClose={() => !busy && setClosing(false)}
        >
          <p>Закрытый кошелёк нельзя открыть снова. Его история сохранится.</p>
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setClosing(false)}
            >
              Отмена
            </button>
            <button
              className="button primary"
              disabled={busy}
              onClick={() => void action("close")}
            >
              Подтвердить закрытие
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

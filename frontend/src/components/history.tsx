"use client";
import { useEffect, useRef, useState } from "react";
import { ListFilter, Search } from "lucide-react";
import { z } from "zod";
import {
  transactionLabel,
  transactionSchema,
  type Page,
  type Transaction,
} from "@/lib/data";
import { api } from "@/lib/api";
import { useFinCore } from "./provider";
import { PageHeading, TransactionList } from "./ui";
export function History() {
  const { state } = useFinCore();
  const [walletId, setWalletId] = useState("");
  const [kind, setKind] = useState("all");
  const [query, setQuery] = useState("");
  const [records, setRecords] = useState<Transaction[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const parameters = new URLSearchParams({ limit: "20" });
  if (walletId) parameters.set("wallet_id", walletId);
  if (kind === "topup") parameters.set("kind", "sandbox_topup");
  else if (kind !== "all") parameters.set("direction", kind);
  const endpoint = `users/me/transactions?${parameters}`;
  useEffect(() => {
    const current = ++generation.current;
    const controller = new AbortController();
    setBusy(true);
    setError("");
    setRecords([]);
    setCursor(null);
    void api<Page<unknown>>(endpoint, { signal: controller.signal })
      .then((page) => {
        if (current === generation.current && !controller.signal.aborted) {
          setRecords(z.array(transactionSchema).parse(page.items));
          setCursor(page.next_cursor);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Ошибка истории.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [endpoint, revision]);
  const filtered = records.filter((t) =>
    `${transactionLabel(t)} ${state.wallets.find((w) => w.id === t.source)?.name || ""} ${state.wallets.find((w) => w.id === t.destination)?.name || ""} ${t.id}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <>
      <PageHeading
        eyebrow="ПРОЗРАЧНО ДО ДЕТАЛЕЙ"
        title="История операций"
        subtitle="Все движения средств. Без потерянных деталей."
      />
      <section className="panel">
        <div className="history-filters">
          <label className="search-field">
            <Search size={18} />
            <input
              aria-label="Поиск операций"
              placeholder="Поиск по загруженным операциям"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label className="filter-select">
            <ListFilter size={16} />
            <select
              aria-label="Фильтр по кошельку"
              value={walletId}
              onChange={(e) => {
                setWalletId(e.target.value);
                if (kind === "internal") setKind("all");
              }}
            >
              <option value="">Все кошельки</option>
              {state.wallets.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="history-tabs" role="group" aria-label="Тип операции">
          {[
            { id: "all", name: "Все операции" },
            ...(!walletId ? [{ id: "internal", name: "Между своими" }] : []),
            { id: "outgoing", name: "Исходящие" },
            { id: "incoming", name: "Входящие" },
            { id: "topup", name: "Пополнения" },
          ].map((tab) => (
            <button
              key={tab.id}
              aria-pressed={kind === tab.id}
              className={kind === tab.id ? "active" : ""}
              onClick={() => setKind(tab.id)}
            >
              {tab.name}
            </button>
          ))}
        </div>
        {error && (
          <p className="error-message" role="alert">
            {error}
            <button
              className="text-link"
              onClick={() => setRevision((v) => v + 1)}
            >
              Повторить
            </button>
          </p>
        )}
        <div className="history-table-heading">
          <span>Операция</span>
          <span>Дата и время</span>
          <span>Сумма</span>
        </div>
        {busy && !records.length ? (
          <p role="status">Загрузка истории…</p>
        ) : (
          <TransactionList transactions={filtered} walletId={walletId} />
        )}
        <div className="history-bottom">
          <span>
            Загружено {records.length} операций
            {query ? ` · найдено ${filtered.length}` : ""}
          </span>
          {cursor && (
            <button
              className="button secondary small"
              disabled={busy}
              onClick={async () => {
                const current = generation.current;
                setBusy(true);
                setError("");
                try {
                  const page = await api<Page<unknown>>(
                    `${endpoint}&cursor=${encodeURIComponent(cursor)}`,
                  );
                  if (current === generation.current) {
                    const items = z.array(transactionSchema).parse(page.items);
                    setRecords((old) => [...old, ...items]);
                    setCursor(page.next_cursor);
                  }
                } catch (e) {
                  if (current === generation.current)
                    setError(
                      e instanceof Error ? e.message : "Ошибка истории.",
                    );
                } finally {
                  if (current === generation.current) setBusy(false);
                }
              }}
            >
              {busy ? "Загрузка…" : "Показать ещё"}
            </button>
          )}
        </div>
      </section>
    </>
  );
}

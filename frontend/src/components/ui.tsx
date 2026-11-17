"use client";
import Link from "next/link";
import {
  ArrowDownLeft,
  ArrowDownUp,
  ArrowUpRight,
  Check,
  ChevronRight,
  Copy,
  Plus,
  Wallet as WalletIcon,
} from "lucide-react";
import {
  money,
  transactionLabel,
  type Transaction,
  type Wallet,
} from "@/lib/data";
import { useFinCore } from "./provider";
import { useEffect, useRef, type ReactNode } from "react";
export function PageHeading({
  eyebrow,
  title,
  subtitle,
  action,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {action}
    </div>
  );
}
export function WalletCard({
  wallet,
  compact = false,
}: {
  wallet: Wallet;
  compact?: boolean;
}) {
  return (
    <Link
      href={`/wallets/${wallet.id}`}
      className={`wallet-card ${wallet.color} ${compact ? "compact" : ""}`}
    >
      <div className="card-top">
        <span className="wallet-symbol">
          <WalletIcon size={22} strokeWidth={1.7} />
        </span>
        <span className="card-currency">
          {wallet.currency} <span className="card-status" />
        </span>
      </div>
      <div className="card-name">
        {wallet.name}
        {wallet.status !== "active" && (
          <small>
            {" "}
            · {wallet.status === "frozen" ? "Заморожен" : "Закрыт"}
          </small>
        )}
      </div>
      <div className="card-amount">
        {money(wallet.balance, wallet.currency)}{" "}
        <small>{wallet.currency}</small>
      </div>
      <div className="card-bottom">
        <span>•• {wallet.number.slice(-4)}</span>
        <ArrowUpRight size={19} />
      </div>
    </Link>
  );
}
export function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <WalletIcon size={30} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
export function CopyButton({ value, label }: { value: string; label: string }) {
  const { notify } = useFinCore();
  return (
    <button
      className="icon-button"
      type="button"
      aria-label={`Скопировать ${label}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          notify("Скопировано");
        } catch {
          notify("Не удалось скопировать. Выделите значение вручную.");
        }
      }}
    >
      <Copy size={17} />
    </button>
  );
}
export function TransactionList({
  transactions,
  walletId,
  limit,
}: {
  transactions: Transaction[];
  walletId?: string;
  limit?: number;
}) {
  const { state } = useFinCore();
  const name = (id: string | null) =>
    state.wallets.find((w) => w.id === id)?.name ||
    (id ? "Другой кошелёк" : "Sandbox");
  if (!transactions.length)
    return (
      <EmptyState
        title="Пока нет операций"
        text="Здесь появится история ваших переводов."
      />
    );
  return (
    <div className="transaction-list">
      {transactions.slice(0, limit).map((t) => {
        const positive = walletId
          ? t.destination === walletId
          : t.kind === "topup" || t.kind === "incoming";
        const negative = walletId
          ? t.source === walletId
          : t.kind === "outgoing";
        const Icon =
          t.kind === "internal"
            ? ArrowDownUp
            : positive
              ? ArrowDownLeft
              : ArrowUpRight;
        const date = new Date(t.date);
        return (
          <Link
            href={
              t.kind === "topup"
                ? `/wallets/${t.destination}`
                : `/transfers/${t.id}`
            }
            className="transaction-row"
            key={t.id}
          >
            <span
              className={`transaction-icon ${t.kind === "internal" ? "neutral" : positive ? "incoming" : "outgoing"}`}
            >
              <Icon size={21} strokeWidth={1.7} />
            </span>
            <span className="transaction-info">
              <strong>{transactionLabel(t)}</strong>
              <small>
                {name(t.source)} <span>→</span> {name(t.destination)}
              </small>
            </span>
            <span className="transaction-date">
              {date.toLocaleDateString("ru-RU", {
                day: "numeric",
                month: "short",
              })}
              <small>
                {date.toLocaleTimeString("ru-RU", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </small>
            </span>
            <span
              className={`transaction-amount ${positive ? "positive" : ""}`}
            >
              {positive ? "+" : negative ? "−" : ""}
              {money(t.amount, t.currency)} <small>{t.currency}</small>
              <span className="transaction-state">
                <Check size={11} /> Выполнен
              </span>
            </span>
            <ChevronRight size={16} className="row-chevron" />
          </Link>
        );
      })}
    </div>
  );
}
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      aria-labelledby="modal-title"
    >
      <div className="modal-content">
        <div className="section-heading">
          <h2 id="modal-title">{title}</h2>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Закрыть"
          >
            <Plus size={22} style={{ transform: "rotate(45deg)" }} />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}

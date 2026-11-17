"use client";
import Link from "next/link";
import {
  ArrowDownUp,
  ArrowRight,
  ArrowUpRight,
  Eye,
  EyeOff,
  Plus,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { useState } from "react";
import { money } from "@/lib/data";
import { useFinCore } from "./provider";
import { PageHeading, TransactionList, WalletCard } from "./ui";
export function Home() {
  const { state, user, balances } = useFinCore();
  const [hidden, setHidden] = useState(false);
  return (
    <>
      <PageHeading
        eyebrow="ВСЁ ПОД КОНТРОЛЕМ"
        title={`С возвращением, ${user?.username}`}
        subtitle="Ваши кошельки и переводы — в одном месте."
        action={<span className="date-chip">Подключено к API</span>}
      />
      <div className="home-overview">
        <section className="balance-panel">
          <div className="balance-heading">
            <span>Общий баланс</span>
            <button
              className="icon-button"
              onClick={() => setHidden((v) => !v)}
              aria-label={
                hidden ? "Показать общий баланс" : "Скрыть общий баланс"
              }
            >
              {hidden ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {balances.totals.length ? (
            balances.totals.map((total) => (
              <div className="total-balance" key={total.currency}>
                {hidden ? "••••••" : money(total.posted_minor, total.currency)}{" "}
                <span>{total.currency}</span>
              </div>
            ))
          ) : (
            <div className="total-balance">
              0,00 <span>CAD</span>
            </div>
          )}
          <div className="balance-caption">
            <span className="status-dot" /> В {state.wallets.length} кошельках ·
            остатки по валютам
          </div>
          <div className="balance-decoration" aria-hidden="true">
            <Wallet size={110} strokeWidth={1} />
          </div>
          <div className="balance-bottom">
            <span>
              <ShieldCheck size={15} /> Виртуальные средства
            </span>
            <Link href="/wallets">
              Все кошельки <ArrowUpRight size={16} />
            </Link>
          </div>
        </section>
        <section className="quick-panel">
          <span className="quick-icon">
            <ArrowDownUp size={24} />
          </span>
          <h2>Деньги в движении</h2>
          <p>Переводите между своими кошельками или другому пользователю.</p>
          <Link href="/transfers/new" className="button primary">
            Новый перевод <ArrowUpRight size={18} />
          </Link>
        </section>
      </div>
      <section className="wallet-section">
        <div className="section-heading">
          <div className="heading-with-count">
            <h2>Мои кошельки</h2>
            <span className="count-badge">{state.wallets.length}</span>
          </div>
          <Link className="text-link" href="/wallets?create=1">
            <Plus size={17} /> Создать кошелёк
          </Link>
        </div>
        <div className="wallet-grid home-wallets">
          {state.wallets.slice(0, 3).map((w) => (
            <WalletCard key={w.id} wallet={w} />
          ))}
        </div>
        {state.wallets.length > 3 && (
          <Link className="text-link more-wallets" href="/wallets">
            Все {state.wallets.length} кошельков <ArrowRight size={16} />
          </Link>
        )}
      </section>
      <section className="panel history-panel">
        <div className="section-heading">
          <div>
            <h2>Последние операции</h2>
            <p className="section-subtitle">Каждый перевод на своём месте</p>
          </div>
          <Link href="/transactions" className="text-link">
            Вся история <ArrowRight size={17} />
          </Link>
        </div>
        <TransactionList transactions={state.transactions} limit={4} />
      </section>
      <div className="demo-footnote">
        <ShieldCheck size={16} />
        <span>
          Данные загружаются из FinCore API. Переводы сохраняются в базе данных;
          все средства виртуальные.
        </span>
      </div>
    </>
  );
}

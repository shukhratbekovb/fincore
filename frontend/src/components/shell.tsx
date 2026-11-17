"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowDownUp,
  ArrowUpRight,
  Check,
  FlaskConical,
  House,
  History as HistoryIcon,
  Info,
  Moon,
  Sun,
  UserRound,
  Wallet,
  X,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useFinCore } from "./provider";
import { AuthScreen } from "./auth";
import type { ReactNode } from "react";
import clsx from "clsx";
const nav = [
  { href: "/", label: "Главная", icon: House },
  { href: "/wallets", label: "Кошельки", icon: Wallet },
  { href: "/transfers/new", label: "Перевод", icon: ArrowDownUp },
  { href: "/transactions", label: "История", icon: HistoryIcon },
  { href: "/profile", label: "Профиль", icon: UserRound },
];
export function Brand() {
  return (
    <span className="brand">
      <span className="brand-symbol">
        <i />
        <i />
        <i />
      </span>
      FinCore<span className="brand-dot">.</span>
    </span>
  );
}
export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { ready, user, notice, notify, error, reload } = useFinCore();
  const { resolvedTheme, setTheme } = useTheme();
  if (!ready)
    return (
      <main className="demo-gate" role="status">
        <Brand />
        <p>Подключаемся к FinCore…</p>
      </main>
    );
  if (!user || pathname === "/confirm" || pathname === "/reset-password")
    return (
      <main className="demo-gate">
        <Link href="/">
          <Brand />
        </Link>
        <AuthScreen key={pathname} />
      </main>
    );
  const initial = user.username[0].toUpperCase();
  const links = nav.map(({ href, label, icon: Icon }) => {
    const current =
      href === "/"
        ? pathname === href
        : pathname.startsWith(href === "/transfers/new" ? "/transfers" : href);
    return (
      <Link
        key={href}
        href={href}
        aria-label={label}
        aria-current={current ? "page" : undefined}
        className={clsx("nav-item", {
          selected: current,
          "transfer-nav": href === "/transfers/new",
        })}
      >
        <span className="nav-icon">
          <Icon size={21} strokeWidth={1.8} />
        </span>
        <span>{label}</span>
        {current && <span className="nav-dot" />}
      </Link>
    );
  });
  return (
    <div className="app-frame">
      <a className="skip-link" href="#main">
        К содержимому
      </a>
      <aside className="sidebar">
        <Link href="/" aria-label="FinCore — Главная">
          <Brand />
        </Link>
        <div className="workspace-label">ЛИЧНЫЙ КАБИНЕТ</div>
        <nav aria-label="Основная навигация">{links}</nav>
        <div className="sidebar-bottom">
          <div className="sandbox-note">
            <span className="sandbox-icon">
              <FlaskConical size={20} />
            </span>
            <strong>Пространство для проб</strong>
            <p>
              Здесь можно экспериментировать.
              <br />
              Все средства — виртуальные.
            </p>
            <span>
              FinCore Sandbox <ArrowUpRight size={14} />
            </span>
          </div>
          <Link href="/profile" className="user-mini">
            <span className="avatar">{initial}</span>
            <span>
              <strong>{user.username}</strong>
              <small>{user.email}</small>
            </span>
            <ArrowUpRight size={17} />
          </Link>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <Link href="/" className="mobile-brand">
            <Brand />
          </Link>
          <span className="desktop-breadcrumb">
            Личный кабинет <span>/</span>{" "}
            <b>
              {nav.find((n) => n.href === pathname)?.label ||
                (pathname.startsWith("/wallets/") ? "Кошелёк" : "Операция")}
            </b>
          </span>
          <div className="topbar-actions">
            <span className="sandbox-pill">
              <span /> Sandbox<span className="sandbox-detail"> · API</span>
            </span>
            <button
              className="icon-button"
              aria-label="Переключить тему"
              onClick={() =>
                setTheme(resolvedTheme === "dark" ? "light" : "dark")
              }
            >
              {ready && resolvedTheme === "dark" ? (
                <Sun size={20} />
              ) : (
                <Moon size={20} />
              )}
            </button>
            <Link
              className="avatar top-avatar"
              href="/profile"
              aria-label="Мой профиль"
            >
              {initial}
            </Link>
          </div>
        </header>
        <main id="main" className="main-content">
          {error && (
            <div role="status" className="storage-warning">
              <Info size={18} />
              {error}
              <button
                className="text-link"
                onClick={() => void reload().catch(() => {})}
              >
                Повторить
              </button>
            </div>
          )}
          {ready ? (
            children
          ) : (
            <div className="loading-screen" role="status">
              <div className="skeleton" />
              <div className="skeleton" />
              <span>Загружаем кошельки…</span>
            </div>
          )}
          <footer className="page-footer">
            <span>© 2026 FinCore</span>
            <span>
              <span className="status-dot" /> Только виртуальные средства
            </span>
          </footer>
        </main>
      </div>
      <nav className="mobile-nav" aria-label="Мобильная навигация">
        {links}
      </nav>
      {notice && (
        <div className="toast" role="status">
          <Check size={18} />
          {notice}
          <button aria-label="Закрыть уведомление" onClick={() => notify("")}>
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

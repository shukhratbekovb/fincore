"use client";
import { useCallback, useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Check, LogOut, Monitor, Moon, ShieldCheck, Sun } from "lucide-react";
import { api } from "@/lib/api";
import type { Session } from "@/lib/data";
import { useFinCore } from "./provider";
import { CopyButton, Modal, PageHeading } from "./ui";
export function Profile() {
  const { theme, setTheme } = useTheme();
  const { user, logout, forget, notify } = useFinCore();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [confirm, setConfirm] = useState<"logout" | "sessions" | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const loadSessions = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const result = await api<Session[]>("users/me/sessions", { signal });
      if (!signal?.aborted) setSessions(result);
    } catch (e) {
      if (!signal?.aborted)
        setError(e instanceof Error ? e.message : "Ошибка сессий.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void loadSessions(controller.signal);
    return () => controller.abort();
  }, [loadSessions]);
  if (!user) return null;
  return (
    <>
      <PageHeading
        eyebrow="ВАШЕ ПРОСТРАНСТВО"
        title="Профиль и настройки"
        subtitle="Сделайте FinCore удобным для себя."
      />
      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      <div className="profile-grid">
        <section className="panel profile-card">
          <span className="avatar profile-avatar">
            {user.username[0].toUpperCase()}
          </span>
          <h2>{user.username}</h2>
          <p>{user.email}</p>
          <span className="active-badge">
            <span className="status-dot" /> Аккаунт активен
          </span>
          <div className="profile-card-divider" />
          <div className="profile-meta">
            <span>Зарегистрирован</span>
            <strong>
              {new Date(user.created_at).toLocaleDateString("ru-RU")}
            </strong>
          </div>
          <div className="profile-security">
            <ShieldCheck size={18} />
            <span>
              Данные загружаются из API.
              <br />
              Токены хранятся в HttpOnly cookies.
            </span>
          </div>
          <span className="muted">ID пользователя</span>
          <div className="copy-field">
            <code>{user.id}</code>
            <CopyButton value={user.id} label="ID пользователя" />
          </div>
        </section>
        <div className="settings-column">
          <section className="panel theme-panel">
            <h2>Оформление</h2>
            <div className="theme-options">
              {[
                { id: "light", label: "Светлая", icon: Sun },
                { id: "dark", label: "Тёмная", icon: Moon },
                { id: "system", label: "Системная", icon: Monitor },
              ].map(({ id, label, icon: Icon }) => (
                <button
                  className={`theme-option ${theme === id ? "selected" : ""}`}
                  key={id}
                  aria-pressed={theme === id}
                  onClick={() => setTheme(id)}
                >
                  <div className={`theme-preview preview-${id}`}>
                    <i />
                    <div>
                      <b />
                      <b />
                      <b />
                    </div>
                  </div>
                  <span>
                    <Icon size={16} />
                    {label}
                    <span className="theme-radio">
                      {theme === id && <Check size={11} />}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </section>
          <section className="panel">
            <h2>Изменить пароль</h2>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (busy) return;
                setBusy(true);
                setError("");
                try {
                  await api("auth/change-password", {
                    method: "POST",
                    body: {
                      current_password: currentPassword,
                      new_password: newPassword,
                    },
                  });
                  setCurrentPassword("");
                  setNewPassword("");
                  notify(
                    "Пароль изменён. Все сессии завершены — войдите снова.",
                  );
                  forget();
                } catch (e) {
                  setError(
                    e instanceof Error
                      ? e.message
                      : "Не удалось изменить пароль.",
                  );
                } finally {
                  setBusy(false);
                }
              }}
            >
              <label className="field">
                Текущий пароль
                <input
                  required
                  type="password"
                  autoComplete="current-password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                />
              </label>
              <label className="field">
                Новый пароль
                <input
                  required
                  minLength={8}
                  maxLength={256}
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                />
              </label>
              <p className="form-footnote">
                От 8 символов, заглавная и строчная буквы, цифра и специальный
                символ. После смены потребуется войти снова на всех устройствах.
              </p>
              <button className="button secondary" disabled={busy}>
                Изменить пароль
              </button>
            </form>
          </section>
          <button
            className="logout-button"
            onClick={() => setConfirm("logout")}
          >
            <LogOut size={18} /> Выйти из аккаунта
          </button>
        </div>
      </div>
      <section className="panel sessions-panel">
        <div className="section-heading">
          <h2>Активные сессии</h2>
          <button
            className="button secondary small"
            disabled={busy || loading}
            onClick={() => setConfirm("sessions")}
          >
            Завершить все сессии
          </button>
        </div>
        {loading ? (
          <p role="status">Загрузка сессий…</p>
        ) : sessions.length ? (
          sessions.map((session) => (
            <div className="session-row" key={session.id}>
              <div>
                <strong>
                  {session.last_user_agent ||
                    session.user_agent ||
                    "Неизвестное устройство"}
                </strong>
                <p>
                  IP: {session.last_ip_address || session.ip_address} · Вход:{" "}
                  {new Date(session.created_at).toLocaleString("ru-RU")}
                </p>
                <small className="muted">
                  Последняя активность:{" "}
                  {new Date(
                    session.last_used_at || session.created_at,
                  ).toLocaleString("ru-RU")}
                </small>
              </div>
              <button
                className="button ghost small"
                disabled={busy}
                aria-label={`Завершить сессию ${session.id}`}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    await api(`users/me/sessions/${session.id}`, {
                      method: "DELETE",
                    });
                    await loadSessions();
                    notify("Сессия завершена");
                  } catch (e) {
                    setError(
                      e instanceof Error
                        ? e.message
                        : "Ошибка завершения сессии.",
                    );
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Завершить
              </button>
            </div>
          ))
        ) : (
          <p>Нет активных сессий.</p>
        )}
      </section>
      {confirm && (
        <Modal
          title={
            confirm === "logout"
              ? "Выйти из аккаунта?"
              : "Завершить все сессии?"
          }
          onClose={() => !busy && setConfirm(null)}
        >
          <p>
            Для продолжения потребуется снова войти{" "}
            {confirm === "sessions" ? "на всех устройствах" : "в аккаунт"}.
          </p>
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setConfirm(null)}
            >
              Отмена
            </button>
            <button
              className="button primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  if (confirm === "logout") await logout();
                  else {
                    await api("users/me/sessions", { method: "DELETE" });
                    forget();
                  }
                  setConfirm(null);
                } catch (e) {
                  setError(e instanceof Error ? e.message : "Ошибка выхода.");
                  setConfirm(null);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {confirm === "logout" ? "Выйти" : "Завершить все"}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

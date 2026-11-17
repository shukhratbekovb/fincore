"use client";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useFinCore } from "./provider";

type Mode = "login" | "register" | "forgot" | "confirm" | "reset" | "resend";
export function AuthScreen() {
  const pathname = usePathname();
  const router = useRouter();
  const { login, notice, error: connectionError, reload } = useFinCore();
  const [mode, setMode] = useState<Mode>(
    pathname === "/confirm"
      ? "confirm"
      : pathname === "/reset-password"
        ? "reset"
        : "login",
  );
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [generated, setGenerated] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const secret = new URLSearchParams(location.hash.slice(1)).get("token");
    if (secret) {
      setToken(secret);
      history.replaceState(null, "", location.pathname);
    }
  }, []);
  const changeMode = (value: Mode) => {
    if (busy) return;
    setMode(value);
    setError("");
    setMessage("");
    setPassword("");
    setGenerated("");
  };
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (mode === "login") {
        await login(username, password);
        router.replace("/");
      }
      if (mode === "register") {
        await api("auth/register", {
          method: "POST",
          body: { username, email },
        });
        setMessage(
          "Письмо отправлено. Откройте ссылку в письме и задайте пароль.",
        );
      }
      if (mode === "forgot") {
        await api("auth/password-reset/request", {
          method: "POST",
          body: { email },
        });
        setMessage(
          "Если аккаунт существует и доступен для сброса, на почту придёт ссылка.",
        );
      }
      if (mode === "resend") {
        await api("auth/confirm/resend", {
          method: "POST",
          body: { email },
        });
        setMessage(
          "Если аккаунт ожидает подтверждения, на почту придёт новая ссылка. Предыдущая ссылка перестанет работать.",
        );
      }
      if (mode === "confirm") {
        await api("auth/confirm", {
          method: "POST",
          body: { token, password },
        });
        setToken("");
        setPassword("");
        setMode("login");
        setMessage("Почта подтверждена. Войдите с вашим логином и паролем.");
      }
      if (mode === "reset") {
        const result = await api<{ password: string }>(
          "auth/password-reset/confirm",
          { method: "POST", body: { token } },
        );
        setToken("");
        setGenerated(result.password);
        setMessage(
          "Пароль изменён. Сохраните новый пароль — он отображается только сейчас.",
        );
      }
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure.message
          : failure instanceof Error
            ? failure.message
            : "Не удалось выполнить запрос.",
      );
    } finally {
      setBusy(false);
    }
  }
  const title = {
    login: "Войти в FinCore",
    register: "Создать аккаунт",
    forgot: "Восстановить доступ",
    confirm: "Подтвердить почту",
    reset: "Получить новый пароль",
    resend: "Отправить подтверждение повторно",
  }[mode];
  return (
    <section className="panel auth-panel">
      <span className="eyebrow">FINCORE · ЛИЧНЫЙ КАБИНЕТ</span>
      <h1>{title}</h1>
      <p className="muted">
        Кошельки и операции сохраняются на сервере. Все средства — виртуальные.
      </p>
      {(message || notice) && (
        <p className="success-message" role="status">
          {message || notice}
        </p>
      )}
      {connectionError && (
        <div className="error-message" role="alert">
          {connectionError}
          <button
            className="text-link"
            onClick={() => void reload().catch(() => {})}
          >
            Повторить подключение
          </button>
        </div>
      )}
      {generated ? (
        <>
          <label className="field">
            Новый пароль
            <input readOnly value={generated} autoComplete="off" />
          </label>
          <button
            className="button primary full"
            onClick={() => changeMode("login")}
          >
            Я сохранил пароль — войти
          </button>
        </>
      ) : (
        <form onSubmit={submit}>
          {(mode === "login" || mode === "register") && (
            <label className="field">
              Логин
              <input
                required
                minLength={5}
                maxLength={256}
                pattern="[a-zA-Z][a-zA-Z0-9_]*[a-zA-Z0-9]"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
          )}
          {(mode === "register" || mode === "forgot" || mode === "resend") && (
            <label className="field">
              Электронная почта
              <input
                type="email"
                required
                maxLength={512}
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
          )}
          {(mode === "confirm" || mode === "reset") && (
            <label className="field">
              Токен из письма
              <input
                required
                type="password"
                autoComplete="off"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
              <span className="field-hint">
                Обычно подставляется автоматически из ссылки.
              </span>
            </label>
          )}
          {(mode === "login" || mode === "confirm") && (
            <label className="field">
              {mode === "confirm" ? "Новый пароль" : "Пароль"}
              <input
                aria-label={mode === "confirm" ? "Новый пароль" : "Пароль"}
                type="password"
                required
                minLength={mode === "confirm" ? 8 : 1}
                maxLength={256}
                autoComplete={
                  mode === "confirm" ? "new-password" : "current-password"
                }
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {mode === "confirm" && (
                <span className="field-hint">
                  От 8 символов: заглавная и строчная буквы, цифра и специальный
                  символ.
                </span>
              )}
            </label>
          )}
          {error && (
            <p className="error-message" role="alert">
              {error}
            </p>
          )}
          <button
            className="button primary full"
            type="submit"
            disabled={
              busy ||
              Boolean(
                message &&
                (mode === "register" || mode === "forgot" || mode === "resend"),
              )
            }
          >
            {busy
              ? "Подождите…"
              : {
                  login: "Войти",
                  register: "Зарегистрироваться",
                  forgot: "Отправить ссылку",
                  confirm: "Подтвердить почту",
                  reset: "Сгенерировать новый пароль",
                  resend: "Отправить новую ссылку",
                }[mode]}
          </button>
        </form>
      )}
      <div className="auth-links">
        {(mode === "login" || mode === "register" || mode === "confirm") && (
          <button
            className="text-link"
            disabled={busy}
            onClick={() => changeMode("resend")}
          >
            Не пришло письмо подтверждения?
          </button>
        )}
        {mode !== "login" && (
          <button className="text-link" onClick={() => changeMode("login")}>
            Уже есть аккаунт — войти
          </button>
        )}
        {mode === "login" && (
          <>
            <button
              className="text-link"
              onClick={() => changeMode("register")}
            >
              Создать аккаунт
            </button>
            <button className="text-link" onClick={() => changeMode("forgot")}>
              Забыли пароль?
            </button>
          </>
        )}
      </div>
      <p className="form-footnote">
        {process.env.NODE_ENV === "development" && (
          <>
            Локальная почта:{" "}
            <a href="http://127.0.0.1:8025" target="_blank" rel="noreferrer">
              Mailpit
            </a>
            .{" "}
          </>
        )}
        <Link href="/">На главную</Link>
      </p>
    </section>
  );
}

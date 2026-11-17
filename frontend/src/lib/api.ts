export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId?: string,
    public retryAfter?: string,
  ) {
    super(message);
  }
}

const messages: Record<string, string> = {
  invalid_credentials: "Неверный логин или пароль.",
  user_inactive: "Сначала подтвердите почту.",
  email_already_exists: "Эта почта уже зарегистрирована.",
  username_already_exists: "Этот логин уже занят.",
  invalid_password:
    "Пароль должен содержать от 8 символов, заглавную и строчную буквы, цифру и специальный символ.",
  invalid_username:
    "Логин: от 5 символов, латинские буквы, цифры и _. Начните с буквы, закончите буквой или цифрой.",
  invalid_confirmation_token: "Ссылка подтверждения недействительна.",
  confirmation_token_expired: "Срок ссылки подтверждения истёк.",
  confirmation_token_used: "Эта ссылка уже использована. Попробуйте войти.",
  invalid_password_reset_token:
    "Ссылка сброса пароля недействительна или истекла.",
  insufficient_funds: "Недостаточно доступных средств.",
  wallet_not_active: "Кошелёк заморожен или закрыт.",
  wallet_closed: "Кошелёк закрыт.",
  wallet_balance_not_zero: "Для закрытия баланс кошелька должен быть нулевым.",
  wallet_not_found: "Кошелёк не найден или недоступен.",
  transfer_not_found: "Перевод не найден или недоступен.",
  transfer_currency_mismatch: "Валюты кошельков должны совпадать.",
  sandbox_disabled:
    "Пополнение отключено. Для локальной проверки включите SANDBOX_ENABLED в backend.",
  sandbox_operator_required:
    "Для пополнения нужно право sandbox-оператора. Команда назначения указана в инструкции frontend.",
  idempotency_conflict: "Ключ уже использован для другого запроса.",
  idempotency_in_progress:
    "Запрос ещё выполняется. Повторите его с теми же данными.",
  backend_unavailable: "Backend недоступен. Проверьте, что API запущен.",
  rate_limiter_unavailable: "Сервис лимитов временно недоступен.",
};

let refreshing: Promise<boolean> | null = null;
async function refreshSession() {
  if (!refreshing) {
    const refresh = async () => {
      // Recheck after acquiring a cross-tab lock: another tab may have rotated.
      const probe = await fetch("/api/backend/users/me", { cache: "no-store" });
      if (probe.ok) return true;
      if (probe.status >= 500)
        throw new ApiError(
          probe.status,
          "backend_unavailable",
          messages.backend_unavailable,
        );
      if (probe.status !== 401) return false;
      const refreshed = await fetch("/api/backend/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (refreshed.status >= 500)
        throw new ApiError(
          refreshed.status,
          "backend_unavailable",
          messages.backend_unavailable,
        );
      return refreshed.ok;
    };
    refreshing = (
      navigator.locks
        ? navigator.locks.request("fincore-refresh", refresh)
        : refresh()
    ).finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

export async function api<T = void>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    key?: string;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const init: RequestInit = {
    method: options.method || "GET",
    cache: "no-store",
    signal: options.signal,
    headers: {
      ...(options.body !== undefined
        ? { "Content-Type": "application/json" }
        : {}),
      ...(options.key ? { "Idempotency-Key": options.key } : {}),
    },
    ...(options.body !== undefined
      ? { body: JSON.stringify(options.body) }
      : {}),
  };
  let response: Response;
  try {
    response = await fetch(`/api/backend/${path}`, init);
    const protectedRoute =
      !path.startsWith("auth/") || path === "auth/change-password";
    const invalidPassword =
      path === "auth/change-password" &&
      response.status === 401 &&
      (
        await response
          .clone()
          .json()
          .catch(() => null)
      )?.detail?.code === "invalid_credentials";
    if (response.status === 401 && protectedRoute && !invalidPassword) {
      if (await refreshSession())
        response = await fetch(`/api/backend/${path}`, init);
      if (response.status === 401)
        window.dispatchEvent(new Event("fincore:unauthorized"));
    }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "network_error",
      "Нет связи с сервером. Проверьте подключение и повторите запрос.",
    );
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const code = data?.detail?.code || "request_failed";
    const message =
      response.status === 429
        ? "Слишком много запросов. Подождите перед повтором."
        : messages[code] ||
          (response.status === 401
            ? "Сессия завершена. Войдите снова."
            : response.status === 422
              ? "Проверьте введённые данные."
              : response.status >= 500
                ? "Ошибка сервера. Повторите позже."
                : "Не удалось выполнить запрос.");
    throw new ApiError(
      response.status,
      code,
      message,
      response.headers.get("x-request-id") || undefined,
      response.headers.get("retry-after") || undefined,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

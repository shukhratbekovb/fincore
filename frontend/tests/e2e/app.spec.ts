import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// These tests use the real local API and Mailpit; all created data is synthetic.
const username = `ui_check_${Date.now().toString(36)}`;
const email = `${username}@example.com`;
let password = "UiCheck2026!";
let walletA = "";
let walletB = "";
let userId = "";
const backend = path.resolve(process.cwd(), "../backend");
async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("Логин", { exact: true }).fill(username);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: `С возвращением, ${username}` }),
  ).toBeVisible();
}
async function mailToken(page: Page, reset = false) {
  let result = "";
  await expect
    .poll(
      async () => {
        const listing = await (
          await page.request.get("http://127.0.0.1:8025/api/v1/messages")
        ).json();
        for (const message of listing.messages || []) {
          if (
            !message.To?.some((r: { Address: string }) => r.Address === email)
          )
            continue;
          const detail = await (
            await page.request.get(
              `http://127.0.0.1:8025/api/v1/message/${message.ID}`,
            )
          ).json();
          const urls =
            (detail.Text || "").match(/https?:\/\/[^\s<>"']+/g) || [];
          for (const link of urls) {
            const url = new URL(link);
            if (url.pathname === (reset ? "/reset-password" : "/confirm"))
              result =
                new URLSearchParams(url.hash.slice(1)).get("token") || "";
          }
          if (result) break;
        }
        return Boolean(result);
      },
      { timeout: 20000 },
    )
    .toBe(true);
  return result;
}

test.describe.serial("real frontend → API → PostgreSQL", () => {
  test("registration/email, wallets, uncertain transfer replay, freeze and server history", async ({
    page,
    context,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await page
      .getByRole("button", { name: "Создать аккаунт", exact: true })
      .click();
    await page.getByLabel("Логин", { exact: true }).fill(username);
    await page.getByLabel("Электронная почта").fill(email);
    await page.getByRole("button", { name: "Зарегистрироваться" }).click();
    await expect(page.getByRole("status")).toContainText("Письмо отправлено");
    const token = await mailToken(page);
    await page.goto(`/confirm#token=${encodeURIComponent(token)}`);
    await expect(page.getByLabel("Токен из письма")).toHaveValue(token);
    await expect(page).toHaveURL(/\/confirm$/);
    await page.getByLabel("Новый пароль", { exact: true }).fill(password);
    await page
      .getByRole("button", { name: "Подтвердить почту", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText("Почта подтверждена");
    await login(page);
    const cookies = await context.cookies();
    expect(
      cookies
        .filter((c) => c.name.startsWith("fincore_"))
        .every((c) => c.httpOnly && c.sameSite === "Lax"),
    ).toBe(true);
    expect(await page.evaluate(() => document.cookie)).not.toContain(
      "fincore_access",
    );
    const me = await (await page.request.get("/api/backend/users/me")).json();
    userId = me.id;
    execFileSync(
      "poetry",
      [
        "run",
        "python",
        "-m",
        "backend.bootstrap.sandbox",
        "--operator-user-id",
        userId,
      ],
      {
        cwd: backend,
        env: { ...process.env, PYTHONPATH: "src" },
        stdio: "pipe",
      },
    );
    for (const [name, currency] of [
      ["Основной API", "CAD"],
      ["Накопления API", "CAD"],
      ["Пустой USD", "USD"],
    ]) {
      await page.goto("/wallets?create=1");
      await page.getByLabel("Название", { exact: true }).fill(name);
      await page.getByLabel("Валюта", { exact: true }).selectOption(currency);
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Создать кошелёк", exact: true })
        .click();
      await expect(page.getByRole("dialog")).not.toBeVisible();
    }
    const wallets = await (
      await page.request.get("/api/backend/wallets")
    ).json();
    walletA = wallets.find(
      (w: { name: string }) => w.name === "Основной API",
    ).id;
    walletB = wallets.find(
      (w: { name: string }) => w.name === "Накопления API",
    ).id;
    console.info("[e2e] Wallet operations");
    await page.goto(`/wallets/${walletA}`);
    await page.getByLabel("Сумма пополнения (CAD)").fill("500");
    await page.getByRole("button", { name: "Пополнить", exact: true }).click();
    await expect(page.locator(".card-amount")).toContainText("500,00");
    await page.goto(`/transfers/new?source=${walletA}`);
    await page.getByLabel("Кошелёк получателя").selectOption(walletB);
    await page.getByLabel("Сумма", { exact: true }).fill("50,25");
    await page.getByRole("button", { name: "Продолжить", exact: true }).click();
    let lostResponse = true;
    const keys: string[] = [];
    await page.route("**/api/backend/transfers", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      keys.push(route.request().headers()["idempotency-key"]);
      const response = await route.fetch();
      if (lostResponse) {
        lostResponse = false;
        return route.abort("failed");
      }
      return route.fulfill({ response });
    });
    await page.getByRole("button", { name: "Подтвердить перевод" }).click();
    await expect(page.locator(".error-message")).toContainText("Нет связи");
    console.info("[e2e] Retry after lost response");
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Всё верно?" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Подтвердить перевод" }).click();
    await expect(
      page.getByRole("heading", { name: "Перевод выполнен" }),
    ).toBeFocused();
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
    const balance = await (
      await page.request.get(`/api/backend/wallets/${walletA}/balance`)
    ).json();
    expect(balance.posted_minor).toBe("44975");
    await page.getByRole("link", { name: "Детали операции" }).click();
    await expect(
      page.getByRole("heading", { name: "Между своими кошельками" }),
    ).toBeVisible();
    await page.reload();
    await expect(page.locator(".review-amount")).toContainText("50,25");
    await page.goto(`/wallets/${walletA}`);
    await page.getByLabel("Новое название").fill("Основной переименован");
    await page
      .getByRole("button", { name: "Переименовать", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Основной переименован", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Заморозить", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Разморозить", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Пополнить", exact: true }),
    ).toBeDisabled();
    const frozen = await page.request.post("/api/backend/transfers", {
      headers: { "Idempotency-Key": crypto.randomUUID() },
      data: {
        sender_wallet_id: walletA,
        receiver_wallet_id: walletB,
        amount_minor: "1",
        currency: "CAD",
      },
    });
    expect(frozen.status()).toBe(409);
    await page
      .getByRole("button", { name: "Разморозить", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Заморозить", exact: true }),
    ).toBeVisible();
    console.info("[e2e] Server history pagination");
    // Create enough real journal rows to exercise cursor pagination.
    for (let index = 0; index < 20; index++) {
      const response = await page.request.post("/api/backend/transfers", {
        headers: { "Idempotency-Key": crypto.randomUUID() },
        data: {
          sender_wallet_id: walletA,
          receiver_wallet_id: walletB,
          amount_minor: "1",
          currency: "CAD",
        },
      });
      expect(response.status()).toBe(201);
    }
    await page.goto("/transactions");
    await expect(page.locator(".transaction-row")).toHaveCount(20);
    await page.getByRole("button", { name: "Показать ещё" }).click();
    await expect(page.locator(".transaction-row")).toHaveCount(22);
    await page.getByLabel("Фильтр по кошельку").selectOption(walletB);
    await expect(
      page.locator(".transaction-row").first().locator(".transaction-amount"),
    ).toContainText("+");
    const empty = wallets.find(
      (w: { name: string }) => w.name === "Пустой USD",
    );
    await page.goto(`/wallets/${empty.id}`);
    await page
      .getByRole("button", { name: "Закрыть кошелёк", exact: true })
      .click();
    await page.getByRole("button", { name: "Подтвердить закрытие" }).click();
    await expect(page.locator(".active-badge")).toHaveText("Закрыт");
    await page.goto("/");
    await expect(
      page.locator(".total-balance").filter({ hasText: "CAD" }),
    ).toContainText("500,00");
    await page.screenshot({
      path: "test-results/connected-home.png",
      fullPage: true,
    });
    expect(errors).toEqual([]);
    mkdirSync("test-results", { recursive: true });
    writeFileSync(
      "test-results/local-account.json",
      JSON.stringify({ username, userId, email }),
    );
  });

  test("refresh across tabs, responsive screens, theme and logout", async ({
    page,
    context,
  }) => {
    await login(page);
    const cookies = await context.cookies();
    const access = cookies.find((c) => c.name === "fincore_access")!;
    await context.addCookies([{ ...access, expires: 1 }]);
    const second = await context.newPage();
    await Promise.all([page.reload(), second.goto("/")]);
    await expect(
      page.getByRole("heading", { name: `С возвращением, ${username}` }),
    ).toBeVisible();
    await expect(
      second.getByRole("heading", { name: `С возвращением, ${username}` }),
    ).toBeVisible();
    await second.close();
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 950 });
      for (const route of [
        "/",
        "/wallets",
        "/transfers/new",
        "/transactions",
        "/profile",
      ]) {
        await page.goto(route);
        await expect(page.locator("h1")).toBeVisible();
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          `${route} at ${width}px`,
        ).toBe(true);
      }
    }
    await page.getByRole("button", { name: "Тёмная", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page
      .getByRole("button", { name: "Выйти из аккаунта", exact: true })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Выйти", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Войти в FinCore" }),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Войти в FinCore" }),
    ).toBeVisible();
  });

  test("password change, password reset and session revocation", async ({
    page,
  }) => {
    await login(page);
    await page.goto("/profile");
    await expect(page.locator(".session-row").first()).toContainText(
      "127.0.0.1",
    );
    await page.getByLabel("Текущий пароль", { exact: true }).fill(password);
    const changed = "UiChanged2026!";
    await page.getByLabel("Новый пароль", { exact: true }).fill(changed);
    await page
      .getByRole("button", { name: "Изменить пароль", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Войти в FinCore" }),
    ).toBeVisible();
    password = changed;
    await login(page);
    await page.goto("/profile");
    await page
      .getByRole("button", { name: "Завершить все сессии", exact: true })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Завершить все", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Войти в FinCore" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Забыли пароль?" }).click();
    await page.getByLabel("Электронная почта").fill(email);
    await page.getByRole("button", { name: "Отправить ссылку" }).click();
    await expect(page.getByRole("status")).toContainText("придёт ссылка");
    const token = await mailToken(page, true);
    await page.goto(`/reset-password#token=${encodeURIComponent(token)}`);
    await expect(page.getByLabel("Токен из письма")).toHaveValue(token);
    await page
      .getByRole("button", { name: "Сгенерировать новый пароль" })
      .click();
    await expect(
      page.getByLabel("Новый пароль", { exact: true }),
    ).toBeVisible();
    password = await page
      .getByLabel("Новый пароль", { exact: true })
      .inputValue();
    await page
      .getByRole("button", { name: "Я сохранил пароль — войти" })
      .click();
    await login(page);
    // Do not persist or print the generated password.
  });
});

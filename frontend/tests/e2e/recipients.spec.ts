import { execFileSync } from "node:child_process";
import path from "node:path";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

const nonce = Date.now().toString(36);
const password = "RecipientTest2026!";
const senderName = `sender_${nonce}`;
const receiverName = `receiver_${nonce}`;
let sender: APIRequestContext;
let receiver: APIRequestContext;
let source: { wallet_id: string; number: string };
let target: { wallet_id: string; number: string };
let usd: { wallet_id: string; number: string };
let freezeTarget: { wallet_id: string; number: string };

async function createAccount(client: APIRequestContext, username: string) {
  const email = `${username}@example.com`;
  const registration = await client.post("/api/backend/auth/register", {
    data: { username, email },
  });
  expect(registration.status()).toBe(201);
  const { user_id } = await registration.json();
  let token = "";
  await expect
    .poll(
      async () => {
        const listing = await (
          await client.get("http://127.0.0.1:8025/api/v1/messages")
        ).json();
        for (const message of listing.messages || []) {
          if (
            !message.To.some(
              (value: { Address: string }) => value.Address === email,
            )
          )
            continue;
          const mail = await (
            await client.get(
              `http://127.0.0.1:8025/api/v1/message/${message.ID}`,
            )
          ).json();
          for (const link of (mail.Text || "").match(
            /https?:\/\/[^\s<>"']+/g,
          ) || [])
            token =
              new URLSearchParams(new URL(link).hash.slice(1)).get("token") ||
              token;
          if (token) break;
        }
        return Boolean(token);
      },
      { timeout: 20000 },
    )
    .toBe(true);
  expect(
    (
      await client.post("/api/backend/auth/confirm", {
        data: { token, password },
      })
    ).status(),
  ).toBe(204);
  expect(
    (
      await client.post("/api/backend/auth/login", {
        data: { username, password },
      })
    ).status(),
  ).toBe(200);
  return user_id as string;
}

async function createWallet(
  client: APIRequestContext,
  name: string,
  currency = "CAD",
) {
  const response = await client.post("/api/backend/wallets", {
    data: { name, currency },
  });
  expect(response.status()).toBe(201);
  const { wallet_id } = await response.json();
  const wallet = await (
    await client.get(`/api/backend/wallets/${wallet_id}`)
  ).json();
  return { wallet_id, number: wallet.number as string };
}

async function openTransfer(page: Page) {
  await page.request.post("/api/backend/auth/login", {
    data: { username: senderName, password },
  });
  await page.goto(`/transfers/new?source=${source.wallet_id}`);
  await page.getByRole("button", { name: "Пользователю", exact: true }).click();
}

test.beforeAll(async ({ playwright }) => {
  sender = await playwright.request.newContext({
    baseURL: "http://localhost:3000",
  });
  receiver = await playwright.request.newContext({
    baseURL: "http://localhost:3000",
  });
  const senderId = await createAccount(sender, senderName);
  await createAccount(receiver, receiverName);
  source = await createWallet(sender, "Отправитель");
  usd = await createWallet(sender, "Другая валюта", "USD");
  target = await createWallet(receiver, "Чужой кошелёк");
  freezeTarget = await createWallet(receiver, "Проверка заморозки");
  execFileSync(
    "poetry",
    [
      "run",
      "python",
      "-m",
      "backend.bootstrap.sandbox",
      "--operator-user-id",
      senderId,
    ],
    {
      cwd: path.resolve(process.cwd(), "../backend"),
      env: { ...process.env, PYTHONPATH: "src" },
      stdio: "pipe",
    },
  );
  const funded = await sender.post("/api/backend/sandbox/top-ups", {
    headers: { "Idempotency-Key": crypto.randomUUID() },
    data: {
      wallet_id: source.wallet_id,
      currency: "CAD",
      amount_minor: "5000",
    },
  });
  expect(funded.status()).toBe(201);
});
test.afterAll(async () => {
  await sender?.dispose();
  await receiver?.dispose();
});

test("resolves recipient username by number, transfers and copies the wallet number", async ({
  page,
  context,
}) => {
  await openTransfer(page);
  await page
    .getByLabel("Номер кошелька получателя", { exact: true })
    .fill(target.number);
  await expect(page.locator(".recipient-preview")).toContainText(
    `Получатель: ${receiverName}`,
  );
  await expect(page.locator(".recipient-preview")).not.toContainText(
    senderName,
  );
  await page.getByLabel("Сумма", { exact: true }).fill("5");
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await expect(page.locator(".review-summary")).toContainText(receiverName);
  await expect(page.locator(".review-summary")).toContainText(target.number);
  await expect(page.locator(".review-summary")).not.toContainText(
    target.wallet_id,
  );
  await page.getByRole("button", { name: "Подтвердить перевод" }).click();
  await expect(
    page.getByRole("heading", { name: "Перевод выполнен" }),
  ).toBeVisible();
  const posted = await (
    await receiver.get(`/api/backend/wallets/${target.wallet_id}/balance`)
  ).json();
  expect(posted.posted_minor).toBe("500");
  await context.grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: "http://localhost:3000",
  });
  await page.goto(`/wallets/${source.wallet_id}`);
  await page
    .getByRole("button", { name: "Скопировать номер кошелька", exact: true })
    .click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    source.number,
  );
  await expect(page.getByRole("status")).toContainText("Скопировано");
  await page.screenshot({
    path: "test-results/recipient-wallet-number.png",
    fullPage: true,
  });
});

test("discards stale lookup results and blocks missing or incompatible recipients", async ({
  page,
}) => {
  await openTransfer(page);
  let started!: () => void;
  const firstStarted = new Promise<void>((resolve) => {
    started = resolve;
  });
  let oldFinished!: () => void;
  const oldResponseFinished = new Promise<void>((resolve) => {
    oldFinished = resolve;
  });
  await page.route(
    "**/api/backend/transfer-recipients/resolve",
    async (route) => {
      const response = await route.fetch();
      if (route.request().postDataJSON().wallet_number === target.number) {
        started();
        await new Promise((resolve) => setTimeout(resolve, 900));
        try {
          await route.fulfill({ response });
        } catch {
        } finally {
          oldFinished();
        }
      } else await route.fulfill({ response });
    },
  );
  const input = page.getByLabel("Номер кошелька получателя", { exact: true });
  await input.fill(target.number);
  await firstStarted;
  await input.fill(usd.number);
  await expect(page.locator(".recipient-preview")).toContainText(senderName);
  await expect(page.locator(".recipient-preview")).toContainText("USD");
  await oldResponseFinished;
  await expect(page.locator(".recipient-preview")).not.toContainText(
    receiverName,
  );
  await expect(
    page.getByRole("button", { name: "Продолжить", exact: true }),
  ).toBeDisabled();
  await input.fill("0".repeat(20));
  await expect(page.locator(".recipient-preview")).toHaveCount(0);
  await expect(page.locator(".error-message")).toContainText(
    "Кошелёк не найден",
  );
  await input.fill(target.number.slice(0, 19));
  await expect(page.locator(".recipient-preview")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Продолжить", exact: true }),
  ).toBeDisabled();
});

test("transfer checks recipient status again after a successful lookup", async ({
  page,
}) => {
  await openTransfer(page);
  await page
    .getByLabel("Номер кошелька получателя", { exact: true })
    .fill(freezeTarget.number);
  await expect(page.locator(".recipient-preview")).toContainText(receiverName);
  await page.getByLabel("Сумма", { exact: true }).fill("1");
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  expect(
    (
      await receiver.post(
        `/api/backend/wallets/${freezeTarget.wallet_id}/freeze`,
        { data: {} },
      )
    ).status(),
  ).toBe(204);
  try {
    await page.getByRole("button", { name: "Подтвердить перевод" }).click();
    await expect(page.locator(".error-message")).toContainText(
      "заморожен или закрыт",
    );
    expect(
      (
        await (
          await receiver.get(
            `/api/backend/wallets/${freezeTarget.wallet_id}/balance`,
          )
        ).json()
      ).posted_minor,
    ).toBe("0");
  } finally {
    await receiver.post(
      `/api/backend/wallets/${freezeTarget.wallet_id}/unfreeze`,
      { data: {} },
    );
  }
});

import { z } from "zod";

export const currencies = [
  "CAD",
  "USD",
  "EUR",
  "JPY",
  "CHF",
  "GBP",
  "UZS",
  "RUB",
] as const;
export type Currency = (typeof currencies)[number];
export const colors = ["mint", "blue", "peach", "violet"] as const;
const minor = z
  .string()
  .regex(/^\d+$/)
  .transform((value) => BigInt(value));
export const userSchema = z.object({
  id: z.string().uuid(),
  username: z.string(),
  email: z.string(),
  created_at: z.string(),
});
export type User = z.infer<typeof userSchema>;
export const walletSchema = z
  .object({
    id: z.string().uuid(),
    name: z.string(),
    number: z.string(),
    currency: z.enum(currencies),
    balance_minor: minor,
    status: z.enum(["active", "frozen", "closed"]),
  })
  .transform((w) => ({
    ...w,
    balance: w.balance_minor,
    color:
      colors[
        parseInt(w.id.replaceAll("-", "").slice(0, 4), 16) % colors.length
      ],
  }));
export type Wallet = z.infer<typeof walletSchema>;
export const transactionSchema = z
  .object({
    id: z.string().uuid(),
    source_id: z.string().uuid(),
    source_type: z.enum(["p2p_transfer", "sandbox_topup"]),
    sender_wallet_id: z.string().nullable(),
    receiver_wallet_id: z.string(),
    amount_minor: minor,
    currency: z.enum(currencies),
    direction: z.enum(["incoming", "outgoing", "internal"]),
    posted_at: z.string(),
  })
  .transform((t) => ({
    id: t.source_id,
    journalId: t.id,
    source: t.sender_wallet_id,
    destination: t.receiver_wallet_id,
    amount: t.amount_minor,
    currency: t.currency,
    kind: t.source_type === "sandbox_topup" ? ("topup" as const) : t.direction,
    date: t.posted_at,
  }));
export type Transaction = z.infer<typeof transactionSchema>;
export const walletRecipientSchema = z.object({
  wallet_id: z.string().uuid(),
  number: z.string().regex(/^[0-9]{20}$/),
  currency: z.enum(currencies),
  owner: z.string().min(1).max(256),
});
export type WalletRecipient = z.infer<typeof walletRecipientSchema>;
export type Command = {
  key: string;
  source: string;
  destination: string;
  amount: bigint;
  currency: Currency;
  recipient?: WalletRecipient;
};
export type Page<T> = { items: T[]; next_cursor: string | null };
export type Session = {
  id: string;
  ip_address: string;
  user_agent: string | null;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  last_ip_address: string | null;
  last_user_agent: string | null;
};
export const balanceSchema = z.object({
  totals: z.array(
    z.object({
      currency: z.enum(currencies),
      posted_minor: minor,
      spendable_minor: minor,
    }),
  ),
  as_of: z.string(),
});
export type Balances = z.infer<typeof balanceSchema>;
export const walletBalanceSchema = z.object({
  posted_minor: minor,
  available_minor: minor,
  spendable_minor: minor,
});
export const MAX_MINOR = 9223372036854775807n;
export function decimals(currency: Currency) {
  return currency === "JPY" ? 0 : 2;
}
export function money(minor: bigint, currency: Currency = "CAD") {
  const digits = decimals(currency);
  const factor = 10n ** BigInt(digits);
  const whole = minor / factor;
  const fraction = (minor % factor).toString().padStart(digits, "0");
  return (
    new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(whole) +
    (digits ? `,${fraction}` : "")
  );
}
export function parseMoney(input: string, currency: Currency = "CAD"): bigint {
  const digits = decimals(currency);
  const value = input.trim().replace(",", ".");
  if (!(digits ? /^\d+(\.\d{1,2})?$/ : /^\d+$/).test(value))
    throw new Error(
      digits
        ? "Введите сумму с точностью до двух знаков, например 50,00."
        : "Для JPY введите целое число.",
    );
  const [whole, fraction = ""] = value.split(".");
  if (whole.length > 19) throw new Error("Сумма слишком велика.");
  const amount =
    BigInt(whole) * 10n ** BigInt(digits) +
    BigInt(fraction.padEnd(digits, "0") || "0");
  if (amount <= 0n || amount > MAX_MINOR)
    throw new Error(
      "Сумма должна быть положительной и не превышать лимит API.",
    );
  return amount;
}
export function inputMoney(amount: bigint, currency: Currency) {
  return money(amount, currency).replace(/[\s\u00a0\u202f]/g, "");
}
export function transactionLabel(t: Transaction) {
  return {
    internal: "Между своими кошельками",
    outgoing: "Исходящий перевод",
    incoming: "Входящий перевод",
    topup: "Тестовое пополнение",
  }[t.kind];
}
export function statusLabel(status: Wallet["status"]) {
  return { active: "Активен", frozen: "Заморожен", closed: "Закрыт" }[status];
}

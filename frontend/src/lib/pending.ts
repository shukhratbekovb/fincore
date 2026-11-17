import { z } from "zod";
import {
  currencies,
  MAX_MINOR,
  walletRecipientSchema,
  type Command,
  type Currency,
} from "./data";
const commandSchema = z.object({
  key: z.string().uuid(),
  source: z.string().uuid(),
  destination: z.string().uuid(),
  amount: z
    .string()
    .regex(/^\d+$/)
    .transform(BigInt)
    .refine((v) => v > 0n && v <= MAX_MINOR),
  currency: z.enum(currencies),
  recipient: walletRecipientSchema.optional(),
});
const topUpSchema = z.object({
  key: z.string().uuid(),
  amount: z
    .string()
    .regex(/^\d+$/)
    .transform(BigInt)
    .refine((v) => v > 0n && v <= MAX_MINOR),
  currency: z.enum(currencies),
});
export type TopUp = { key: string; amount: bigint; currency: Currency };
export function savePending(key: string, command: Command | TopUp) {
  try {
    sessionStorage.setItem(
      key,
      JSON.stringify({ ...command, amount: command.amount.toString() }),
    );
  } catch {
    throw new Error(
      "Не удалось сохранить ключ запроса. Разрешите sessionStorage и повторите — деньги ещё не отправлены.",
    );
  }
}
export function readPending(key: string): Command | null;
export function readPending(key: string, topUp: true): TopUp | null;
export function readPending(key: string, topUp = false) {
  try {
    const raw = sessionStorage.getItem(key);
    return raw
      ? (topUp ? topUpSchema : commandSchema).parse(JSON.parse(raw))
      : null;
  } catch {
    return null;
  }
}
export function clearPending(key: string) {
  try {
    sessionStorage.removeItem(key);
  } catch {}
}

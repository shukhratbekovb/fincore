import { describe, expect, it } from "vitest";
import {
  inputMoney,
  MAX_MINOR,
  money,
  parseMoney,
  transactionSchema,
  walletSchema,
} from "../src/lib/data";
const id = "869a2d1e-6c4b-4e91-a198-345678901001";
describe("exact API money", () => {
  it("parses decimal strings without floating point and formats 64-bit amounts", () => {
    expect(parseMoney("0,29")).toBe(29n);
    expect(parseMoney("92233720368547758.07")).toBe(MAX_MINOR);
    expect(money(MAX_MINOR)).toBe("92 233 720 368 547 758,07");
    expect(inputMoney(MAX_MINOR, "CAD")).toBe("92233720368547758,07");
    for (const value of [
      "0",
      "-1",
      "NaN",
      "0.001",
      "1e3",
      "92233720368547758.08",
    ])
      expect(() => parseMoney(value)).toThrow();
  });
  it("uses integer minor units for JPY", () => {
    expect(parseMoney("150", "JPY")).toBe(150n);
    expect(money(150n, "JPY")).toBe("150");
    expect(() => parseMoney("1.1", "JPY")).toThrow();
  });
  it("requires decimal string balances and retains large wallet values", () => {
    const input = {
      id,
      number: "00001234567890123456",
      name: "Main",
      status: "active",
      currency: "CAD",
      balance_minor: MAX_MINOR.toString(),
    };
    expect(walletSchema.parse(input).balance).toBe(MAX_MINOR);
    expect(() =>
      walletSchema.parse({ ...input, balance_minor: Number(MAX_MINOR) }),
    ).toThrow();
  });
  it("keeps journal and business IDs separate for transaction details", () => {
    const sourceId = "2bb6fc41-90ea-4d03-b541-000000000004";
    const result = transactionSchema.parse({
      id,
      source_id: sourceId,
      source_type: "p2p_transfer",
      sender_wallet_id: id,
      receiver_wallet_id: sourceId,
      amount_minor: "25",
      currency: "CAD",
      direction: "incoming",
      posted_at: new Date().toISOString(),
    });
    expect(result.id).toBe(sourceId);
    expect(result.journalId).toBe(id);
    expect(result.amount).toBe(25n);
    expect(result.kind).toBe("incoming");
  });
});

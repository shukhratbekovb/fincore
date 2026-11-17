import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPending, readPending, savePending } from "../src/lib/pending";
const command = {
  key: "2bb6fc41-90ea-4d03-b541-000000000004",
  source: "869a2d1e-6c4b-4e91-a198-345678901001",
  destination: "869a2d1e-6c4b-4e91-a198-345678901002",
  amount: 9223372036854775807n,
  currency: "CAD" as const,
};
beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  });
});
afterEach(() => vi.unstubAllGlobals());
describe("pending monetary requests", () => {
  it("keeps recipient number and username with an uncertain transfer across reloads", () => {
    const recipient = {
      wallet_id: command.destination,
      number: "00001234567890123456",
      currency: "CAD" as const,
      owner: "receiver_user",
    };
    savePending("fincore.transfer.v1.alice", { ...command, recipient });
    expect(readPending("fincore.transfer.v1.alice")).toEqual({
      ...command,
      recipient,
    });
  });
  it("retains the exact command and key across remounts, isolated by user key", () => {
    savePending("fincore.transfer.v1.alice", command);
    expect(readPending("fincore.transfer.v1.alice")).toEqual(command);
    expect(readPending("fincore.transfer.v1.bob")).toBeNull();
    clearPending("fincore.transfer.v1.alice");
    expect(readPending("fincore.transfer.v1.alice")).toBeNull();
  });
  it("rejects corrupt and out-of-range persisted commands", () => {
    sessionStorage.setItem(
      "key",
      JSON.stringify({ ...command, amount: "9223372036854775808" }),
    );
    expect(readPending("key")).toBeNull();
    sessionStorage.setItem("key", "bad-json");
    expect(readPending("key")).toBeNull();
  });
  it("blocks submission when the retry key cannot be persisted", () => {
    vi.stubGlobal("sessionStorage", {
      setItem: () => {
        throw new Error("QuotaExceeded");
      },
      getItem: () => {
        throw new Error("SecurityError");
      },
    });
    expect(() => savePending("key", command)).toThrow(
      "деньги ещё не отправлены",
    );
    expect(readPending("key")).toBeNull();
  });
  it("restores top-ups without a fabricated balance", () => {
    const pending = {
      key: command.key,
      amount: 2500n,
      currency: "CAD" as const,
    };
    savePending("topup", pending);
    expect(readPending("topup", true)).toEqual(pending);
  });
});

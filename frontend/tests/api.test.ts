import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";
import { api, ApiError } from "../src/lib/api";
let expired: Mock<() => void>;
beforeEach(() => {
  const events = new EventTarget();
  expired = vi.fn<() => void>();
  events.addEventListener("fincore:unauthorized", expired);
  vi.stubGlobal("window", events);
  vi.stubGlobal("navigator", {});
});
afterEach(() => vi.unstubAllGlobals());
const invalid = () =>
  Response.json({ detail: { code: "invalid_access_token" } }, { status: 401 });
describe("browser API session handling", () => {
  it("refreshes once for concurrent requests and retries each request", async () => {
    let rotated = false;
    const fetch = vi.fn(async (url: string) => {
      if (url.endsWith("auth/refresh")) {
        rotated = true;
        return Response.json({ authenticated: true });
      }
      return rotated ? Response.json({ ok: true }) : invalid();
    });
    vi.stubGlobal("fetch", fetch);
    const result = await Promise.all([
      api("wallets"),
      api("users/me/balances"),
    ]);
    expect(result).toEqual([{ ok: true }, { ok: true }]);
    expect(
      fetch.mock.calls.filter(([url]) => url.endsWith("auth/refresh")),
    ).toHaveLength(1);
    expect(expired).not.toHaveBeenCalled();
  });
  it("keeps session state on a temporary refresh failure and reports the outage", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("auth/refresh")
          ? Response.json({}, { status: 503 })
          : invalid(),
      ),
    );
    await expect(api("wallets")).rejects.toMatchObject({
      status: 503,
      code: "backend_unavailable",
    });
    expect(expired).not.toHaveBeenCalled();
  });
  it("does not rotate or log out when the current password is wrong", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        Response.json(
          { detail: { code: "invalid_credentials" } },
          { status: 401 },
        ),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(
      api("auth/change-password", { method: "POST", body: {} }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(expired).not.toHaveBeenCalled();
  });
});

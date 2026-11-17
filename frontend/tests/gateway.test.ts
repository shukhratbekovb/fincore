import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET as handle } from "../src/app/api/backend/[...path]/route";
const context = (path: string) => ({
  params: Promise.resolve({ path: path.split("/") }),
});
function request(
  path: string,
  method = "GET",
  options: ConstructorParameters<typeof NextRequest>[1] = {},
) {
  return new NextRequest(`http://localhost:3000/api/backend/${path}`, {
    method,
    ...options,
  });
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
describe("authenticated gateway", () => {
  it.each(["198.51.100.20", "2001:db8::20"])(
    "forwards only the authenticated ingress address %s",
    async (clientIp) => {
      const token = "a".repeat(64);
      vi.stubEnv("NODE_ENV", "production");
      vi.stubEnv("FRONTEND_TRUSTED_PROXY_TOKEN", token);
      vi.stubEnv("PUBLIC_APP_ORIGIN", "https://fincore.example");
      const fetch = vi.fn().mockResolvedValue(Response.json({}));
      vi.stubGlobal("fetch", fetch);
      const response = await handle(
        request("auth/register", "POST", {
          headers: {
            Host: "spoofed.test",
            Origin: "https://fincore.example",
            "Content-Type": "application/json",
            "X-FinCore-Proxy-Token": token,
            "X-Real-IP": clientIp,
            "X-Forwarded-For": "192.0.2.99, 10.0.0.1",
            "X-Forwarded-Proto": "http",
          },
          body: "{}",
        }),
        context("auth/register"),
      );
      expect(response.status).toBe(200);
      const headers = fetch.mock.calls[0][1].headers;
      expect(headers.get("x-forwarded-for")).toBe(clientIp);
      expect(headers.get("x-forwarded-proto")).toBe("https");
      expect(headers.has("x-fincore-proxy-token")).toBe(false);
      expect(headers.has("x-real-ip")).toBe(false);
    },
  );
  it.each([
    [undefined, undefined, undefined, undefined, 503],
    ["short", "https://fincore.example", "short", "198.51.100.20", 503],
    [
      "a".repeat(64),
      "http://fincore.example",
      "a".repeat(64),
      "198.51.100.20",
      503,
    ],
    [
      "a".repeat(64),
      "https://fincore.example",
      undefined,
      "198.51.100.20",
      403,
    ],
    [
      "a".repeat(64),
      "https://fincore.example",
      "b".repeat(64),
      "198.51.100.20",
      403,
    ],
    [
      "a".repeat(64),
      "https://fincore.example",
      "a".repeat(64),
      "198.51.100.20, 10.0.0.1",
      400,
    ],
    [
      "a".repeat(64),
      "https://fincore.example",
      "a".repeat(64),
      "fe80::1%eth0",
      400,
    ],
  ])(
    "rejects unauthenticated or invalid production proxy metadata",
    async (token, origin, provided, ip, expected) => {
      vi.stubEnv("NODE_ENV", "production");
      vi.stubEnv("FRONTEND_TRUSTED_PROXY_TOKEN", token);
      vi.stubEnv("PUBLIC_APP_ORIGIN", origin);
      const headers = new Headers();
      if (provided) headers.set("X-FinCore-Proxy-Token", provided);
      if (ip) headers.set("X-Real-IP", ip);
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      const response = await handle(
        request("wallets", "GET", { headers }),
        context("wallets"),
      );
      expect(response.status).toBe(expected);
      expect(fetch).not.toHaveBeenCalled();
    },
  );
  it("rejects forged Host origins even through an authenticated proxy", async () => {
    const token = "a".repeat(64);
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("FRONTEND_TRUSTED_PROXY_TOKEN", token);
    vi.stubEnv("PUBLIC_APP_ORIGIN", "https://fincore.example");
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const response = await handle(
      request("auth/register", "POST", {
        headers: {
          Host: "evil.test",
          Origin: "http://evil.test",
          "X-FinCore-Proxy-Token": token,
          "X-Real-IP": "198.51.100.20",
        },
      }),
      context("auth/register"),
    );
    expect(response.status).toBe(403);
    expect(fetch).not.toHaveBeenCalled();
  });
  it("forwards exact recipient numbers in an authenticated POST body", async () => {
    const recipient = {
      wallet_id: "869a2d1e-6c4b-4e91-a198-345678901002",
      number: "00001234567890123456",
      currency: "CAD",
      owner: "receiver_user",
    };
    const fetch = vi.fn().mockResolvedValue(Response.json(recipient));
    vi.stubGlobal("fetch", fetch);
    const response = await handle(
      request("transfer-recipients/resolve", "POST", {
        headers: {
          "Content-Type": "application/json",
          Cookie: "fincore_access=token",
        },
        body: JSON.stringify({ wallet_number: recipient.number }),
      }),
      context("transfer-recipients/resolve"),
    );
    expect(await response.json()).toEqual(recipient);
    expect(fetch.mock.calls[0][0]).not.toContain(recipient.number);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      wallet_number: recipient.number,
    });
    expect(fetch.mock.calls[0][1].headers.get("authorization")).toBe(
      "Bearer token",
    );
  });
  it("accepts the actual Host origin when Next.js normalizes loopback URLs", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(Response.json({ user_id: "id" }, { status: 201 })),
    );
    const response = await handle(
      request("auth/register", "POST", {
        headers: {
          Host: "127.0.0.1:3000",
          Origin: "http://127.0.0.1:3000",
          "Content-Type": "application/json",
        },
        body: "{}",
      }),
      context("auth/register"),
    );
    expect(response.status).toBe(201);
  });
  it("keeps login tokens in HttpOnly cookies and out of the response body", async () => {
    const fetch = vi.fn().mockResolvedValue(
      Response.json({
        access_token: "access-secret",
        refresh_token: "refresh-secret",
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const response = await handle(
      request("auth/login", "POST", {
        headers: {
          "Content-Type": "application/json",
          Origin: "http://localhost:3000",
        },
        body: JSON.stringify({ username: "alice", password: "Secret9!" }),
      }),
      context("auth/login"),
    );
    expect(await response.json()).toEqual({ authenticated: true });
    const cookies = response.headers.get("set-cookie")!;
    expect(cookies).toContain("HttpOnly");
    expect(cookies).toContain("SameSite=lax");
    expect(fetch.mock.calls[0][1].headers.has("authorization")).toBe(false);
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
  it("uses only the refresh cookie and forwards client agent without trusting IP headers", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        Response.json({ access_token: "a", refresh_token: "r" }),
      );
    vi.stubGlobal("fetch", fetch);
    await handle(
      request("auth/refresh", "POST", {
        headers: {
          Cookie: "fincore_refresh=server-token",
          "X-Forwarded-For": "1.2.3.4",
          "User-Agent": "Test browser",
        },
        body: '{"refresh_token":"forged"}',
      }),
      context("auth/refresh"),
    );
    const init = fetch.mock.calls[0][1];
    expect(JSON.parse(init.body)).toEqual({ refresh_token: "server-token" });
    expect(init.headers.get("user-agent")).toBe("Test browser");
    expect(init.headers.has("x-forwarded-for")).toBe(false);
  });
  it("rejects cross-site mutations, arbitrary paths and missing authentication before fetch", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect(
      (
        await handle(
          request("auth/logout", "POST", {
            headers: { Origin: "http://evil.test" },
          }),
          context("auth/logout"),
        )
      ).status,
    ).toBe(403);
    expect((await handle(request("../docs"), context("../docs"))).status).toBe(
      404,
    );
    expect((await handle(request("wallets"), context("wallets"))).status).toBe(
      401,
    );
    expect(fetch).not.toHaveBeenCalled();
  });
  it("forwards the same idempotency key and exact string amount, never browser auth", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        Response.json(
          { transfer_id: "id" },
          { status: 201, headers: { "X-Request-ID": "correlation" } },
        ),
      );
    vi.stubGlobal("fetch", fetch);
    const body = { amount_minor: "9223372036854775807" };
    const response = await handle(
      request("transfers", "POST", {
        headers: {
          "Content-Type": "application/json",
          Cookie: "fincore_access=actual",
          Authorization: "Bearer forged",
          "Idempotency-Key": "stable",
        },
        body: JSON.stringify(body),
      }),
      context("transfers"),
    );
    const init = fetch.mock.calls[0][1];
    expect(init.headers.get("authorization")).toBe("Bearer actual");
    expect(init.headers.get("idempotency-key")).toBe("stable");
    expect(JSON.parse(init.body)).toEqual(body);
    expect(response.status).toBe(201);
    expect(response.headers.get("x-request-id")).toBe("correlation");
  });
  it("clears cookies after password change and returns no body for 204", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );
    const response = await handle(
      request("auth/change-password", "POST", {
        headers: {
          "Content-Type": "application/json",
          Cookie: "fincore_access=actual",
        },
        body: "{}",
      }),
      context("auth/change-password"),
    );
    expect(response.status).toBe(204);
    expect(await response.text()).toBe("");
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
  });
  it("redacts transport failures and preserves rate-limit headers", async () => {
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new Error("postgres://sensitive"));
    vi.stubGlobal("fetch", fetch);
    const response = await handle(
      request("wallets", "GET", { headers: { Cookie: "fincore_access=a" } }),
      context("wallets"),
    );
    expect(response.status).toBe(502);
    expect(await response.text()).not.toContain("sensitive");
    fetch.mockResolvedValueOnce(
      Response.json(
        { detail: { code: "rate_limit_exceeded" } },
        { status: 429, headers: { "Retry-After": "30" } },
      ),
    );
    const limited = await handle(
      request("wallets", "GET", { headers: { Cookie: "fincore_access=a" } }),
      context("wallets"),
    );
    expect(limited.status).toBe(429);
    expect(limited.headers.get("retry-after")).toBe("30");
  });
});

import { NextRequest, NextResponse } from "next/server";
import { trustedProxyContext } from "../../../../lib/proxy";

export const runtime = "nodejs";
const ACCESS = "fincore_access";
const REFRESH = "fincore_refresh";
const routes: Record<string, RegExp[]> = {
  GET: [
    /^users\/me(?:\/(?:sessions|transactions|balances))?$/,
    /^wallets(?:\/[a-f0-9-]{36}(?:\/(?:balance|transactions))?)?$/i,
    /^transfers(?:\/[a-f0-9-]{36})?$/i,
  ],
  POST: [
    /^transfer-recipients\/resolve$/,
    /^auth\/(?:login|register|confirm(?:\/resend)?|refresh|logout|change-password|password-reset\/(?:request|confirm))$/,
    /^wallets(?:\/[a-f0-9-]{36}\/(?:close|freeze|unfreeze))?$/i,
    /^transfers$/,
    /^sandbox\/top-ups$/,
  ],
  PATCH: [/^wallets\/[a-f0-9-]{36}$/i],
  DELETE: [/^users\/me\/sessions(?:\/[a-f0-9-]{36})?$/i],
};
type Context = { params: Promise<{ path: string[] }> };

function error(code: string, status: number) {
  return NextResponse.json(
    { detail: { code, message: code, errors: [] } },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

function clearSession(response: NextResponse) {
  for (const name of [ACCESS, REFRESH])
    response.cookies.set(name, "", {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: 0,
    });
}

async function handle(request: NextRequest, context: Context) {
  const path = (await context.params).path.join("/");
  if (!routes[request.method]?.some((pattern) => pattern.test(path)))
    return error("not_found", 404);
  const proxy = trustedProxyContext(request.headers);
  if (!proxy.ok) return error(proxy.code, proxy.status);
  if (request.method !== "GET") {
    const origin = request.headers.get("origin");
    // Next.js normalizes loopback hostnames in nextUrl; Host retains the
    // browser's actual origin (localhost and 127.0.0.1 have different cookies).
    const expectedOrigin =
      proxy.origin ||
      `${request.nextUrl.protocol}//${request.headers.get("host") || request.nextUrl.host}`;
    if (
      request.headers.get("sec-fetch-site") === "cross-site" ||
      (origin && origin !== expectedOrigin)
    )
      return error("invalid_origin", 403);
  }
  const publicRoute =
    path.startsWith("auth/") && path !== "auth/change-password";
  const access = request.cookies.get(ACCESS)?.value;
  const refresh = request.cookies.get(REFRESH)?.value;
  if (!publicRoute && !access) return error("invalid_access_token", 401);
  if (path === "auth/refresh" && !refresh)
    return error("invalid_refresh_token", 401);
  if (path === "auth/logout" && !refresh) {
    const response = new NextResponse(null, {
      status: 204,
      headers: { "Cache-Control": "no-store" },
    });
    clearSession(response);
    return response;
  }
  const headers = new Headers({
    "User-Agent": request.headers.get("user-agent") || "FinCore Web",
  });
  if (proxy.clientIp) {
    headers.set("X-Forwarded-For", proxy.clientIp);
    headers.set("X-Forwarded-Proto", "https");
  }
  if (access && !publicRoute) headers.set("Authorization", `Bearer ${access}`);
  const key = request.headers.get("idempotency-key");
  if (key) headers.set("Idempotency-Key", key);
  let body: string | undefined;
  if (path === "auth/refresh" || path === "auth/logout") {
    body = JSON.stringify({ refresh_token: refresh });
  } else if (request.method === "POST" || request.method === "PATCH") {
    if (Number(request.headers.get("content-length") || 0) > 32768)
      return error("request_too_large", 413);
    if (
      request.headers.get("content-type")?.split(";")[0] !== "application/json"
    )
      return error("invalid_json", 415);
    body = await request.text();
    if (new TextEncoder().encode(body).length > 32768)
      return error("request_too_large", 413);
    try {
      JSON.parse(body);
    } catch {
      return error("invalid_json", 400);
    }
  }
  if (body !== undefined) headers.set("Content-Type", "application/json");
  try {
    const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
    const upstream = await fetch(
      `${base.replace(/\/$/, "")}/v1/${path}${request.nextUrl.search}`,
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(15000),
      },
    );
    const responseHeaders = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["Content-Type", "X-Request-ID", "Retry-After"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    if (upstream.ok && (path === "auth/login" || path === "auth/refresh")) {
      const tokens = await upstream.json();
      if (
        typeof tokens.access_token !== "string" ||
        typeof tokens.refresh_token !== "string"
      )
        return error("invalid_backend_response", 502);
      const response = NextResponse.json(
        { authenticated: true },
        { headers: responseHeaders },
      );
      for (const [name, value] of [
        [ACCESS, tokens.access_token],
        [REFRESH, tokens.refresh_token],
      ]) {
        response.cookies.set(name, value, {
          httpOnly: true,
          sameSite: "lax",
          secure: process.env.NODE_ENV === "production",
          path: "/",
        });
      }
      return response;
    }
    const response = new NextResponse(
      upstream.status === 204 ? null : await upstream.text(),
      { status: upstream.status, headers: responseHeaders },
    );
    if (
      (upstream.ok &&
        [
          "auth/logout",
          "auth/change-password",
          "auth/password-reset/confirm",
        ].includes(path)) ||
      (upstream.ok &&
        request.method === "DELETE" &&
        path === "users/me/sessions") ||
      (path === "auth/refresh" && [401, 403].includes(upstream.status))
    )
      clearSession(response);
    return response;
  } catch {
    return error("backend_unavailable", 502);
  }
}

export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };

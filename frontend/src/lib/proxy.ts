import { timingSafeEqual } from "node:crypto";
import { isIP } from "node:net";

type ProxyContext =
  | { ok: true; origin?: string; clientIp?: string }
  | { ok: false; code: string; status: number };

// Route Handlers do not expose the socket peer. A server-only secret authenticates
// the ingress instead: Nginx must overwrite both headers, never append them.
// Development ignores every forwarded header unless explicitly configured.
export function trustedProxyContext(headers: Headers): ProxyContext {
  const token = process.env.FRONTEND_TRUSTED_PROXY_TOKEN;
  const origin = process.env.PUBLIC_APP_ORIGIN;
  if (!token && process.env.NODE_ENV !== "production") return { ok: true };
  if (!token || token.length < 32 || !origin)
    return { ok: false, code: "proxy_not_configured", status: 503 };
  try {
    const url = new URL(origin);
    if (url.protocol !== "https:" || url.origin !== origin)
      return { ok: false, code: "proxy_not_configured", status: 503 };
  } catch {
    return { ok: false, code: "proxy_not_configured", status: 503 };
  }
  const provided = headers.get("x-fincore-proxy-token") || "";
  const expectedBytes = Buffer.from(token);
  const providedBytes = Buffer.from(provided);
  if (
    expectedBytes.length !== providedBytes.length ||
    !timingSafeEqual(expectedBytes, providedBytes)
  )
    return { ok: false, code: "untrusted_proxy", status: 403 };
  const clientIp = headers.get("x-real-ip") || "";
  // A single address only: lists, ports, zones, and forwarded chains are rejected.
  if (!isIP(clientIp) || clientIp.includes("%"))
    return { ok: false, code: "invalid_client_ip", status: 400 };
  return { ok: true, origin, clientIp };
}

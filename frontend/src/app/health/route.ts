export const dynamic = "force-dynamic";

// Liveness only; the API owns readiness checks for PostgreSQL and Redis.
export function GET() {
  return Response.json(
    { status: "ok" },
    { headers: { "Cache-Control": "no-store" } },
  );
}

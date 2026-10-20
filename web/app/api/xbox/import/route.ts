import { createClient } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";
import { XBOX_IMPORT_COOKIE, openImportSession, xboxConfigFromEnv } from "@/lib/auth/xbox";
import { importXboxLibrary, type ImportDb } from "@/lib/library/xboxImport";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * POST /api/xbox/import — imports the signed-in user's Xbox games into their library.
 * REQ014 · TM11-56.
 *
 * /api/xbox/callback (with intent=import) puts a 5-minute Xbox session in an encrypted
 * httpOnly cookie; the Settings page then calls this with its Supabase bearer token. The
 * route checks the session's XUID is the one this user linked, reads the title history,
 * and hands it to the GameGPT API with the same bearer token.
 *
 * The cookie is cleared after use, on every response. That only removes it from the
 * browser: a copied value would still open until it expires, which is why it is
 * encrypted and short-lived, and why the XUID check runs on every call.
 */

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** Server-to-server base URL for the GameGPT API. API_URL wins so a deploy can use a
 * private address; otherwise the same URL the browser uses. */
function apiUrlFromEnv(env: NodeJS.ProcessEnv = process.env): string {
  return env.API_URL?.trim() || env.NEXT_PUBLIC_API_URL?.trim() || "http://localhost:8000";
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const respond = (status: number, body: Record<string, unknown>) => {
    const res = NextResponse.json(body, { status });
    res.cookies.delete({ name: XBOX_IMPORT_COOKIE, path: "/api/xbox" });
    return res;
  };

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const config = xboxConfigFromEnv();
  if (!url || !anonKey || !config) return respond(500, { reason: "config" });

  const token = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization")?.trim() ?? "")?.[1];
  if (!token) return respond(401, { reason: "session" });

  const session = openImportSession(request.cookies.get(XBOX_IMPORT_COOKIE)?.value, config);
  if (!session) return respond(400, { reason: "expired" });

  const supabase = createClient(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: { headers: { Authorization: `Bearer ${token}` } },
  });

  const outcome = await importXboxLibrary({
    db: supabase as unknown as ImportDb,
    session,
    accessToken: token,
    apiUrl: apiUrlFromEnv(),
  });
  if (outcome.status === "imported") return respond(200, outcome.summary);
  return respond(outcome.httpStatus, { reason: outcome.reason });
}

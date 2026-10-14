import { createClient } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";
import { XBOX_LINK_COOKIE, openIdentity, xboxConfigFromEnv } from "@/lib/auth/xbox";
import { persistXboxLink, type LinkDb } from "@/lib/account/linkXbox";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * POST /api/xbox/link — attaches the identity /api/xbox/callback verified to the signed-in
 * user and writes their platform_accounts row (platform XBOX). REQ014 · TM11-53 (AC1).
 *
 * Acts as the caller via their own JWT, never a service-role key, so RLS is what limits the
 * write to their own row. The sealed identity cookie is single-use: it is cleared on every
 * response, success or not.
 */

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const respond = (status: number, body: Record<string, unknown>) => {
    const res = NextResponse.json(body, { status });
    res.cookies.delete({ name: XBOX_LINK_COOKIE, path: "/api/xbox" });
    return res;
  };

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const config = xboxConfigFromEnv();
  if (!url || !anonKey || !config) return respond(500, { reason: "config" });

  const token = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization")?.trim() ?? "")?.[1];
  if (!token) return respond(401, { reason: "session" });

  const identity = openIdentity(request.cookies.get(XBOX_LINK_COOKIE)?.value, config);
  if (!identity) return respond(400, { reason: "expired" });

  const supabase = createClient(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: { headers: { Authorization: `Bearer ${token}` } },
  });

  const outcome = await persistXboxLink(supabase as unknown as LinkDb, identity);
  if (outcome.status === "linked") return respond(200, { gamertag: outcome.gamertag });
  return respond(outcome.httpStatus, { reason: outcome.reason });
}

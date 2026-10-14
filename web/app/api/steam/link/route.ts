import { createClient } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";
import {
  STEAM_LINK_COOKIE,
  STEAM_LINK_COOKIE_PATH,
  openSteamId,
  steamLinkSecretFromEnv,
} from "@/lib/auth/steamLink";
import type { LinkDb } from "@/lib/account/linkXbox";
import { persistSteamLink } from "@/lib/account/linkSteam";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * POST /api/steam/link — attaches the steamID64 /api/steam/callback verified to the
 * signed-in user and writes their platform_accounts row (platform STEAM). TM11-52.
 *
 * Mirrors POST /api/xbox/link: acts as the caller via their own JWT, never a service-role
 * key, and the sealed identity cookie is single-use, cleared on every response.
 */

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const respond = (status: number, body: Record<string, unknown>) => {
    const res = NextResponse.json(body, { status });
    res.cookies.delete({ name: STEAM_LINK_COOKIE, path: STEAM_LINK_COOKIE_PATH });
    return res;
  };

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const secret = steamLinkSecretFromEnv();
  if (!url || !anonKey || !secret) {
    return respond(500, { reason: "config" });
  }

  const token = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization")?.trim() ?? "")?.[1];
  if (!token) {
    return respond(401, { reason: "session" });
  }

  const steamId = openSteamId(request.cookies.get(STEAM_LINK_COOKIE)?.value, secret);
  if (!steamId) {
    return respond(400, { reason: "expired" });
  }

  const supabase = createClient(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: { headers: { Authorization: `Bearer ${token}` } },
  });

  const outcome = await persistSteamLink(supabase as unknown as LinkDb, steamId);
  if (outcome.status === "linked") {
    return respond(200, { steamId: outcome.steamId });
  }
  return respond(outcome.httpStatus, { reason: outcome.reason });
}

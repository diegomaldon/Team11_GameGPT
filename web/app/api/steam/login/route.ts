import { NextResponse, type NextRequest } from "next/server";
import { buildSteamAuthUrl } from "@/lib/auth/steam";
import { safeNext } from "@/lib/auth/redirect";
import { originFromRequest } from "@/lib/auth/request-origin";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Steam OpenID — first half. REQ010 · TM11-44.
 *
 * GET /api/steam/login hands the browser to Steam. It runs server-side (a Route Handler
 * rather than the client-side supabase-js the Google flow uses) because the return trip has
 * to be verified server-to-server against Steam, and because the anti-CSRF nonce belongs in
 * an httpOnly cookie the browser cannot read.
 *
 *   1. Mint a random `state` nonce and stash it in an httpOnly cookie.
 *   2. Echo the same nonce on return_to, so the callback can compare the two (AC2).
 *   3. Redirect to Steam with a realm/return_to built from this request's own origin (AC4).
 */

// This handler sets cookies and reads request headers, so it can never be statically cached.
export const dynamic = "force-dynamic";

/** The nonce cookie. Lax so it survives Steam's top-level redirect back to us. */
const STATE_COOKIE = "steam_openid_state";
const STATE_TTL_SECONDS = 600; // 10 minutes is plenty to click through Steam.

export function GET(request: NextRequest): NextResponse {
  const origin = originFromRequest(request);
  const next = safeNext(request.nextUrl.searchParams.get("next"));

  const state = crypto.randomUUID();

  // Steam echoes return_to back verbatim, so our own params ride alongside the openid.* ones
  // it appends. The callback reads `state` from here and matches it to the cookie.
  const returnTo = new URL("/api/steam/callback", origin);
  returnTo.searchParams.set("state", state);
  if (next !== "/") returnTo.searchParams.set("next", next);

  const steamUrl = buildSteamAuthUrl({
    realm: origin,
    returnTo: returnTo.toString(),
  });

  const response = NextResponse.redirect(steamUrl);
  response.cookies.set(STATE_COOKIE, state, {
    httpOnly: true,
    sameSite: "lax",
    secure: origin.startsWith("https://"),
    path: "/",
    maxAge: STATE_TTL_SECONDS,
  });
  return response;
}

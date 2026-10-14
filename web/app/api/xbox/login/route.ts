import { NextResponse, type NextRequest } from "next/server";
import {
  XBOX_STATE_COOKIE,
  XBOX_VERIFIER_COOKIE,
  buildXboxAuthUrl,
  codeChallengeFor,
  createCodeVerifier,
  xboxConfigFromEnv,
  xboxLinkedAccountsResult,
} from "@/lib/auth/xbox";
import { safeNext } from "@/lib/auth/redirect";
import { originFromRequest } from "@/lib/auth/request-origin";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Xbox linking, first half. REQ014 · TM11-53.
 *
 * GET /api/xbox/login hands the browser to Microsoft sign-in. Mirrors /api/steam/login:
 * a random state nonce plus a PKCE verifier go into httpOnly cookies, and the redirect URI
 * is built from this request's own origin so the same code works on localhost and Vercel.
 * Unlike Steam, Microsoft only accepts redirect URIs registered on the Azure app, so each
 * environment's /api/xbox/callback must be added there (docs/auth-xbox.md).
 */

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const COOKIE_TTL_SECONDS = 600;

export function GET(request: NextRequest): NextResponse {
  const origin = originFromRequest(request);
  const next = safeNext(request.nextUrl.searchParams.get("next"));

  const config = xboxConfigFromEnv();
  if (!config) {
    return NextResponse.redirect(
      new URL(xboxLinkedAccountsResult("error", { reason: "config", next }), origin),
    );
  }

  const state = crypto.randomUUID();
  const verifier = createCodeVerifier();
  const redirectUri = new URL("/api/xbox/callback", origin).toString();

  const response = NextResponse.redirect(
    buildXboxAuthUrl({
      clientId: config.clientId,
      redirectUri,
      // `next` rides inside state so the callback can return the user where they started.
      state: next === "/" ? state : `${state}.${encodeURIComponent(next)}`,
      codeChallenge: codeChallengeFor(verifier),
    }),
  );
  const cookie = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: origin.startsWith("https://"),
    path: "/api/xbox",
    maxAge: COOKIE_TTL_SECONDS,
  };
  response.cookies.set(XBOX_STATE_COOKIE, state, cookie);
  response.cookies.set(XBOX_VERIFIER_COOKIE, verifier, cookie);
  return response;
}

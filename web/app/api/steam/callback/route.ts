import { NextResponse, type NextRequest } from "next/server";
import {
  parseSteamCallback,
  verifySteamAssertion,
  extractSteamId,
  linkedAccountsResult,
} from "@/lib/auth/steam";
import { originFromRequest } from "@/lib/auth/request-origin";
import {
  STEAM_LINK_COOKIE,
  STEAM_LINK_COOKIE_PATH,
  STEAM_LINK_TTL_SECONDS,
  sealSteamId,
  steamLinkSecretFromEnv,
} from "@/lib/auth/steamLink";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Steam OpenID — second half. REQ010 · TM11-44.
 *
 * GET /api/steam/callback is where Steam sends the user back. Everything arrives as a normal
 * page load, including the failures (Steam sends mode=cancel, not an HTTP error), so every
 * outcome ends in a redirect back to the linked-accounts page carrying a result the page
 * turns into a message (AC3). Nothing here trusts the claimed identity until Steam confirms
 * it via check_authentication (AC1).
 *
 * TM11-52: the verified steamID64 no longer travels in the URL. It is sealed into a
 * short-lived httpOnly cookie and the page redirects with `steam=verified`; the settings
 * page then calls POST /api/steam/link, which writes platform_accounts for the signed-in
 * user. See lib/auth/steamLink.ts.
 */

export const dynamic = "force-dynamic";

const STATE_COOKIE = "steam_openid_state";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const origin = originFromRequest(request);
  const params = request.nextUrl.searchParams;
  const next = params.get("next");

  // The redirect target is always same-origin; linkedAccountsResult returns a path and
  // safeNext guards `next`, so a tampered return_to cannot bounce the user off-site.
  const back = (path: string) => NextResponse.redirect(new URL(path, origin));
  const clearState = (response: NextResponse) => {
    response.cookies.delete(STATE_COOKIE);
    return response;
  };

  // AC2 — the state we minted at /login must come back unchanged. A missing or mismatched
  // nonce means this callback was not started by us: reject before touching the assertion.
  const expectedState = request.cookies.get(STATE_COOKIE)?.value;
  const returnedState = params.get("state");
  if (!expectedState || !returnedState || expectedState !== returnedState) {
    return clearState(back(linkedAccountsResult("error", { reason: "state", next })));
  }

  const parsed = parseSteamCallback(params);

  if (parsed.status === "cancelled") {
    return clearState(back(linkedAccountsResult("cancelled", { next })));
  }
  if (parsed.status === "error") {
    return clearState(back(linkedAccountsResult("error", { reason: parsed.reason, next })));
  }

  // AC1 — only now, after Steam confirms it issued this assertion, is claimed_id trustworthy.
  const verified = await verifySteamAssertion(parsed.verificationBody);
  if (!verified) {
    return clearState(back(linkedAccountsResult("error", { reason: "verify", next })));
  }

  const steamId = extractSteamId(parsed.claimedId);
  if (!steamId) {
    return clearState(back(linkedAccountsResult("error", { reason: "identity", next })));
  }

  const secret = steamLinkSecretFromEnv();
  if (!secret) {
    return clearState(back(linkedAccountsResult("error", { reason: "config", next })));
  }

  const response = clearState(back(linkedAccountsResult("verified", { next })));
  response.cookies.set(STEAM_LINK_COOKIE, sealSteamId(steamId, secret), {
    httpOnly: true,
    sameSite: "lax",
    secure: origin.startsWith("https://"),
    path: STEAM_LINK_COOKIE_PATH,
    maxAge: STEAM_LINK_TTL_SECONDS,
  });
  return response;
}

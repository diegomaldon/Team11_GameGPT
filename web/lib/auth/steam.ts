import { safeNext } from "./redirect";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Steam OpenID 2.0 sign-in. REQ010 (first half) · TM11-44.
 *
 * Steam does not do OAuth2 — it speaks OpenID 2.0, so there is no PKCE code and nothing
 * that supabase-js can redeem. The flow is still two halves, because it leaves the site:
 *
 *   buildSteamAuthUrl()  — hands the browser to steamcommunity.com (from /api/steam/login).
 *   parseSteamCallback() — runs at /api/steam/callback, decides denial vs. verify vs. ok.
 *   verifySteamAssertion() — asks Steam whether the assertion it just sent us is genuine.
 *
 * The identity Steam asserts (`openid.claimed_id`) is only trustworthy after we echo the
 * whole response back with `mode=check_authentication` and Steam answers `is_valid:true`.
 * Skipping that step means anyone can forge a claimed_id, so the steamID64 is never read
 * until verification passes.
 *
 * These are pure functions on URL / URLSearchParams so the route handlers stay thin and the
 * OpenID rules can be tested without a browser or a network round trip.
 */

/** Steam's OpenID 2.0 endpoint. Used for both the redirect and the verification POST. */
export const STEAM_OPENID_ENDPOINT = "https://steamcommunity.com/openid/login";

/** OpenID 2.0 asks the provider to identify whoever it likes ("identifier select"). */
const OPENID_IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select";
const OPENID_NS = "http://specs.openid.net/auth/2.0";

/** claimed_id always looks like https://steamcommunity.com/openid/id/<steamID64>. */
const CLAIMED_ID_PATTERN = /^https?:\/\/steamcommunity\.com\/openid\/id\/(\d{17})$/;

// ---------------------------------------------------------------------------
// Leaving
// ---------------------------------------------------------------------------

/**
 * Builds the checkid_setup URL that hands the browser to Steam.
 *
 * `realm` is the site Steam shows the user ("Sign in to <realm>") and the scope the
 * assertion is bound to; `returnTo` is where Steam sends them back and must sit under the
 * realm. Both are derived from the incoming request's own origin, never a hardcoded host —
 * that is what makes the flow work on the deployed environment as well as localhost (AC4).
 */
export function buildSteamAuthUrl({
  realm,
  returnTo,
}: {
  realm: string;
  returnTo: string;
}): string {
  const url = new URL(STEAM_OPENID_ENDPOINT);
  url.searchParams.set("openid.ns", OPENID_NS);
  url.searchParams.set("openid.mode", "checkid_setup");
  url.searchParams.set("openid.return_to", returnTo);
  url.searchParams.set("openid.realm", realm);
  // We do not know the steamID64 yet — Steam picks the signed-in user for us.
  url.searchParams.set("openid.identity", OPENID_IDENTIFIER_SELECT);
  url.searchParams.set("openid.claimed_id", OPENID_IDENTIFIER_SELECT);
  return url.toString();
}

// ---------------------------------------------------------------------------
// Coming back
// ---------------------------------------------------------------------------

export type SteamCallback =
  /** Ready to verify with Steam. `verificationBody` is the exact payload to POST back. */
  | { status: "assertion"; claimedId: string; verificationBody: URLSearchParams }
  /** The user backed out on Steam's side. Steam sends mode=cancel, not an HTTP error. */
  | { status: "cancelled" }
  /** Malformed or unexpected response — a direct hit on the callback, or a spent link. */
  | { status: "error"; reason: SteamErrorReason };

export type SteamErrorReason =
  | "state" // the anti-CSRF nonce did not match
  | "mode" // openid.mode was not the id_res we expect
  | "identity" // claimed_id missing or not a Steam identity URL
  | "verify" // Steam did not confirm the assertion
  | "network"; // the verification POST itself failed

/**
 * Reads what Steam sent to /api/steam/callback and decides what to do with it, without yet
 * trusting any of it. The caller has already checked the anti-CSRF state; this looks only
 * at the OpenID fields.
 *
 * Takes the query params rather than the request so it can be tested without a browser.
 */
export function parseSteamCallback(params: URLSearchParams): SteamCallback {
  const mode = params.get("openid.mode");

  // The user pressed "Cancel" on the Steam sign-in page. This comes back as a normal page
  // load, so without handling it the callback would look broken. That is AC3.
  if (mode === "cancel") {
    return { status: "cancelled" };
  }

  // A genuine positive assertion is always mode=id_res. Anything else means someone opened
  // the callback directly, or the link was already consumed.
  if (mode !== "id_res") {
    return { status: "error", reason: "mode" };
  }

  const claimedId = params.get("openid.claimed_id");
  if (!claimedId || !CLAIMED_ID_PATTERN.test(claimedId)) {
    return { status: "error", reason: "identity" };
  }

  return {
    status: "assertion",
    claimedId,
    verificationBody: buildVerificationBody(params),
  };
}

/**
 * Turns Steam's positive assertion into the check_authentication payload. It is the same
 * set of openid.* fields Steam sent, with only the mode swapped — Steam re-checks its own
 * signature against them and tells us whether it really issued them.
 */
export function buildVerificationBody(params: URLSearchParams): URLSearchParams {
  const body = new URLSearchParams();
  for (const [key, value] of params) {
    // Our own params (state, next) ride alongside openid.* on return_to; Steam only signs
    // and expects the openid.* ones, so send just those back.
    if (key.startsWith("openid.")) body.set(key, value);
  }
  body.set("openid.mode", "check_authentication");
  return body;
}

/**
 * Asks Steam to confirm it really issued the assertion. Returns true only on an explicit
 * `is_valid:true`; anything else — including a non-200 or a thrown fetch — is treated as
 * "not verified" rather than allowed through.
 */
export async function verifySteamAssertion(
  verificationBody: URLSearchParams,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  try {
    const res = await fetchImpl(STEAM_OPENID_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: verificationBody.toString(),
    });
    if (!res.ok) return false;
    const text = await res.text();
    // The response is a tiny key-value document; the line that matters is `is_valid:true`.
    return /is_valid\s*:\s*true/i.test(text);
  } catch {
    return false;
  }
}

/**
 * Pulls the 17-digit steamID64 out of a claimed_id. Assumes the id_res has already been
 * verified — returns null rather than throwing so a surprise shape becomes an error page,
 * not a crash.
 */
export function extractSteamId(claimedId: string): string | null {
  const match = CLAIMED_ID_PATTERN.exec(claimedId);
  return match ? match[1] : null;
}

// ---------------------------------------------------------------------------
// Where the callback sends the user afterwards
// ---------------------------------------------------------------------------

/** The linked-accounts page owns every outcome of the flow. AC3. */
const LINKED_ACCOUNTS_PATH = "/settings";

/**
 * Builds the same-origin path the callback redirects to. Every outcome — success, cancel,
 * failure — lands back on the linked-accounts page carrying a `steam` result the page turns
 * into a message. `next` is validated with safeNext so a tampered return_to cannot bounce a
 * user off-site.
 */
export function linkedAccountsResult(
  result: "linked" | "cancelled" | "error",
  extra?: { steamId?: string; reason?: SteamErrorReason; next?: string | null },
): string {
  const url = new URL(LINKED_ACCOUNTS_PATH, "http://placeholder.invalid");
  url.searchParams.set("steam", result);
  if (extra?.steamId) url.searchParams.set("steamid", extra.steamId);
  if (extra?.reason) url.searchParams.set("reason", extra.reason);
  const next = safeNext(extra?.next);
  if (next !== "/") url.searchParams.set("next", next);
  // Return a path, not the placeholder-origin absolute URL.
  return `${url.pathname}${url.search}`;
}

/**
 * Turns a Steam result into something worth showing on the linked-accounts page. Mirrors
 * describeCallbackError in oauth.ts: specific where it helps, and never blames the user for
 * a configuration mistake.
 */
export function describeSteamResult(
  result: string | null,
  reason?: string | null,
): { tone: "success" | "info" | "error"; message: string } | null {
  switch (result) {
    case "linked":
      return { tone: "success", message: "Steam connected. Your library will import shortly." };
    case "cancelled":
      return {
        tone: "info",
        message: "Steam sign-in was cancelled. You can connect again whenever you're ready.",
      };
    case "error":
      return { tone: "error", message: describeSteamErrorReason(reason) };
    default:
      return null;
  }
}

function describeSteamErrorReason(reason?: string | null): string {
  switch (reason) {
    case "state":
      return "That Steam sign-in couldn't be verified as yours. Start again from Connect.";
    case "verify":
      return "Steam couldn't confirm that sign-in. Try connecting again in a moment.";
    case "identity":
    case "mode":
      return "That Steam link is incomplete or already used. Start again from Connect.";
    case "network":
      return "Couldn't reach Steam to finish connecting. Check your connection and try again.";
    default:
      return "Steam connection didn't finish. Try again from Connect.";
  }
}

import { safeNext } from "./redirect";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Xbox linking: failure reasons, the URL the callback returns to, and the messages the
 * Settings page shows. REQ014 · TM11-53 (AC2). Browser-safe: no node imports.
 */

export type XboxErrorReason =
  | "state" // anti-CSRF state or PKCE verifier missing / mismatched
  | "auth" // Microsoft returned an error, or the code exchange failed
  | "no_profile" // Microsoft account has never created an Xbox profile
  | "child" // child account without family permission for Xbox Live
  | "region" // Xbox Live not offered in the account's country
  | "verification" // adult verification required (South Korea)
  | "unsupported" // any other account XSTS refuses
  | "network" // a Microsoft / Xbox endpoint could not be reached
  | "config" // this server has no Azure app registration
  | "taken" // XUID already linked to a different GameGPT user
  | "expired"; // link cookie missing or past its 10 minutes

// ---------------------------------------------------------------------------
// Where the callback sends the user, and what the page says
// ---------------------------------------------------------------------------

export function xboxLinkedAccountsResult(
  result: "verified" | "cancelled" | "error",
  extra?: { reason?: XboxErrorReason; next?: string | null },
): string {
  const url = new URL("/settings", "http://placeholder.invalid");
  url.searchParams.set("xbox", result);
  if (extra?.reason) url.searchParams.set("reason", extra.reason);
  const next = safeNext(extra?.next);
  if (next !== "/") url.searchParams.set("next", next);
  return `${url.pathname}${url.search}`;
}

export function describeXboxResult(
  result: string | null,
  reason?: string | null,
  gamertag?: string | null,
): { tone: "success" | "info" | "error"; message: string } | null {
  switch (result) {
    case "linked":
      return {
        tone: "success",
        message: gamertag ? `Xbox connected as ${gamertag}.` : "Xbox connected.",
      };
    case "cancelled":
      return {
        tone: "info",
        message: "Xbox sign-in was cancelled. You can connect again whenever you're ready.",
      };
    case "error":
      return { tone: "error", message: describeXboxErrorReason(reason) };
    default:
      return null;
  }
}

export function describeXboxErrorReason(reason?: string | null): string {
  switch (reason) {
    case "no_profile":
      return "This Microsoft account doesn't have an Xbox profile yet. Sign in once at xbox.com to create one, then connect again.";
    case "child":
      return "This is a child account. A parent needs to allow Xbox Live for it in Microsoft Family Safety before it can connect.";
    case "region":
      return "Xbox Live isn't available in this Microsoft account's country or region, so it can't be connected.";
    case "verification":
      return "This Microsoft account needs adult verification on xbox.com before it can connect.";
    case "unsupported":
      return "This Microsoft account can't be used with Xbox Live, so it can't be connected.";
    case "taken":
      return "That Xbox account is already linked to a different GameGPT account.";
    case "state":
    case "expired":
      return "That Xbox sign-in couldn't be verified as yours or took too long. Start again from Connect.";
    case "network":
      return "Couldn't reach Xbox to finish connecting. Check your connection and try again.";
    case "config":
      return "Xbox connection isn't set up on this server yet.";
    case "session":
      return "Your GameGPT session expired before Xbox finished connecting. Sign in again, then connect Xbox.";
    case "auth":
    default:
      return "Microsoft sign-in didn't finish. Try connecting again.";
  }
}

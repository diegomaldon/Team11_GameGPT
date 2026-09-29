import { supabase } from "../supabase";
import { scrubError } from "./register";
import { safeNext } from "./redirect";

/**
 * GameGPT · E2 Identity & Account Management
 * Google sign-in. REQ002.
 *
 * Two halves, because OAuth leaves the site in between:
 *
 *   startGoogleSignIn()  — hands the browser to Google.
 *   completeOAuthSignIn() — runs at /auth/callback, trades the code for a session.
 *
 * The client is configured with flowType 'pkce' (lib/supabase.ts), so what comes back is
 * a single-use `code` that only this browser can redeem. Nothing sensitive rides in the
 * URL and nothing needs to be kept between the two halves.
 */

export type StartResult =
  /** The browser is navigating to Google. Nothing after this runs. */
  | { status: "redirecting" }
  | { status: "error"; message: string };

export type CompleteResult =
  | { status: "signed_in"; next: string }
  /** Google or the user said no. `message` is safe to show. */
  | { status: "denied"; message: string }
  | { status: "error"; message: string };

/**
 * The provider is not configured, in this environment, at all. Worth its own message:
 * it means a dashboard setting is missing, not that the visitor did anything wrong, and
 * it is the failure every new team member hits first.
 */
const NOT_CONFIGURED =
  "Google sign-in isn't set up for this environment yet. Use your email and password, or check the Supabase provider settings.";

// ---------------------------------------------------------------------------
// Leaving
// ---------------------------------------------------------------------------

export async function startGoogleSignIn(next?: string | null): Promise<StartResult> {
  // Where to come back to. Carried on the callback URL rather than in storage so it
  // survives the round trip even if the browser discards session storage in between.
  const target = safeNext(next);
  const callback = new URL("/auth/callback", window.location.origin);
  if (target !== "/") callback.searchParams.set("next", target);

  try {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: callback.toString(),
        // Without this Google silently reuses the last account on a shared machine and
        // the user has no way to pick a different one.
        queryParams: { prompt: "select_account" },
      },
    });

    if (error) {
      console.error("[auth] signInWithOAuth failed", scrubError(error));
      if (isProviderDisabled(error.message)) {
        return { status: "error", message: NOT_CONFIGURED };
      }
      return { status: "error", message: "Couldn't start Google sign-in. Try again." };
    }

    return { status: "redirecting" };
  } catch (thrown) {
    const error = thrown instanceof Error ? thrown : new Error("Unknown OAuth failure");
    console.error("[auth] signInWithOAuth threw", scrubError(error));
    return { status: "error", message: "Check your connection and try again." };
  }
}

// ---------------------------------------------------------------------------
// Coming back
// ---------------------------------------------------------------------------

/**
 * Handles whatever /auth/callback was given. Takes the query string rather than reading
 * the URL itself so it can be tested without a browser.
 */
export async function completeOAuthSignIn(
  params: URLSearchParams,
): Promise<CompleteResult> {
  const next = safeNext(params.get("next"));

  // Refusal path. Google redirects back with an error instead of a code when the user
  // cancels, or when the OAuth app is misconfigured on Google's side. This arrives as a
  // normal page load, so without handling it the page would sit there looking broken.
  const error = params.get("error") ?? params.get("error_code");
  if (error) {
    return {
      status: "denied",
      message: describeCallbackError(error, params.get("error_description")),
    };
  }

  const code = params.get("code");
  if (!code) {
    // Landing here with neither a code nor an error usually means someone opened or
    // refreshed the URL directly, after the code was already spent.
    return {
      status: "error",
      message: "That sign-in link is incomplete or already used. Start again from sign-in.",
    };
  }

  try {
    const { data, error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);

    if (exchangeError) {
      console.error("[auth] exchangeCodeForSession failed", scrubError(exchangeError));
      return {
        status: "error",
        message: "We couldn't finish signing you in. Start again from sign-in.",
      };
    }

    if (!data.session) {
      console.error("[auth] exchangeCodeForSession returned no session and no error");
      return {
        status: "error",
        message: "We couldn't finish signing you in. Start again from sign-in.",
      };
    }

    // No navigation here. onAuthStateChange in session.tsx receives the new session and
    // the page decides where to go, same as the password path.
    return { status: "signed_in", next };
  } catch (thrown) {
    const err = thrown instanceof Error ? thrown : new Error("Unknown exchange failure");
    console.error("[auth] exchangeCodeForSession threw", scrubError(err));
    return { status: "error", message: "Check your connection and try again." };
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isProviderDisabled(message: string): boolean {
  return /provider is not enabled|unsupported provider/i.test(message);
}

/**
 * Turns an OAuth error code into something worth showing. The raw
 * `error_description` is written for developers and sometimes names internal config,
 * so it is logged rather than displayed, except where it genuinely is the clearest
 * thing available.
 */
export function describeCallbackError(
  code: string,
  description?: string | null,
): string {
  switch (code) {
    case "access_denied":
      return "Sign-in was cancelled. You can try again or use your email and password.";
    case "provider_email_needs_verification":
      return "Verify your email address with Google first, then try again.";
    case "provider_disabled":
    case "unsupported_provider":
      return NOT_CONFIGURED;
    case "redirect_uri_mismatch":
      // Only ever a setup mistake. Say so plainly instead of blaming the user.
      return "This site's callback URL isn't on the allowed list for Google sign-in. That's a configuration problem, not you.";
    case "server_error":
    case "temporarily_unavailable":
      return "Google couldn't complete sign-in right now. Try again in a moment.";
    default:
      console.error("[auth] unmapped OAuth callback error", { code, description });
      return "Google sign-in didn't complete. Try again, or use your email and password.";
  }
}

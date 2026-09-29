/**
 * GameGPT · E2 Identity & Account Management
 * Platform token revocation. REQ005.
 *
 * "Revoked where the provider allows" is doing real work in that acceptance
 * criterion — the three platforms we link do not behave the same way:
 *
 *   STEAM  OpenID 2.0. Steam asserts an identity and issues no token at all, so
 *          there is nothing to revoke. Unlinking is the whole of it.
 *   EPIC   OAuth 2.0 with a real revocation endpoint. Revocable.
 *   XBOX   OAuth via Microsoft identity platform, which has no token-revocation
 *          endpoint. Access tokens expire on their own and refresh tokens are
 *          only revocable by the user from their Microsoft account page.
 *
 * Reporting "revoked" for Steam would be a lie, and quietly doing nothing for
 * Xbox would be a different lie. Every account gets an explicit outcome and a
 * reason, and the caller passes that back to the UI.
 */

export type PlatformType = "STEAM" | "XBOX" | "EPIC";

export type RevokeOutcome =
  /** The provider confirmed the token is dead. */
  | { platform: PlatformType; status: "revoked" }
  /** Nothing to revoke — no token was ever stored for this account. */
  | { platform: PlatformType; status: "no_token" }
  /** We hold a token but the provider offers no way to revoke it. */
  | { platform: PlatformType; status: "unsupported"; reason: string }
  /** We tried and it failed. The token is still dropped from our database. */
  | { platform: PlatformType; status: "failed"; reason: string };

export type PlatformAccount = {
  platform: PlatformType;
  access_token: string | null;
};

/**
 * What each provider supports. `endpoint: null` means the provider has no
 * revocation mechanism, which is a different fact from "we have no token".
 */
const REVOCATION: Record<
  PlatformType,
  { endpoint: string | null; reason?: string }
> = {
  STEAM: {
    endpoint: null,
    reason: "Steam signs in over OpenID 2.0 and issues no access token.",
  },
  EPIC: {
    endpoint: "https://api.epicgames.dev/epic/oauth/v2/revoke",
  },
  XBOX: {
    endpoint: null,
    reason:
      "Microsoft identity platform exposes no revocation endpoint; tokens expire or are revoked from the user's Microsoft account.",
  },
};

/** How long to wait on a provider before giving up and deleting anyway. */
const REVOKE_TIMEOUT_MS = 5_000;

/**
 * Best effort by design. A provider being down must not be able to block
 * someone from deleting their account — REQ005 says "at any time", and the
 * token is destroyed on our side regardless of what the provider says. A
 * failure here is recorded, not thrown.
 */
export async function revokePlatformTokens(
  accounts: PlatformAccount[],
  fetchImpl: typeof fetch = fetch,
): Promise<RevokeOutcome[]> {
  return Promise.all(
    accounts.map((account) => revokeOne(account, fetchImpl)),
  );
}

async function revokeOne(
  account: PlatformAccount,
  fetchImpl: typeof fetch,
): Promise<RevokeOutcome> {
  const { platform } = account;
  const token = account.access_token?.trim();

  if (!token) return { platform, status: "no_token" };

  const config = REVOCATION[platform];
  if (!config?.endpoint) {
    return {
      platform,
      status: "unsupported",
      reason: config?.reason ?? "No revocation endpoint for this provider.",
    };
  }

  // AbortSignal.timeout rather than a bare fetch: a provider that accepts the
  // connection and then hangs would otherwise stall account deletion
  // indefinitely.
  try {
    const response = await fetchImpl(config.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ token }).toString(),
      signal: AbortSignal.timeout(REVOKE_TIMEOUT_MS),
    });

    if (!response.ok) {
      return {
        platform,
        status: "failed",
        reason: `Provider returned ${response.status}.`,
      };
    }

    return { platform, status: "revoked" };
  } catch (thrown) {
    const reason =
      thrown instanceof Error && thrown.name === "TimeoutError"
        ? "Provider did not respond in time."
        : "Could not reach the provider.";
    return { platform, status: "failed", reason };
  }
}

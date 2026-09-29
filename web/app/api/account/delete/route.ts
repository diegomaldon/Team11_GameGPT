import { createClient } from "@supabase/supabase-js";
import { revokePlatformTokens, type PlatformAccount } from "@/lib/account/revoke";

/**
 * GameGPT · E2 Identity & Account Management
 * POST /api/account/delete — REQ005.
 *
 * Runs on the server for one reason: revoking platform tokens means talking to
 * Epic and friends, and those calls have no business happening from the
 * browser. The deletion itself is a SECURITY DEFINER function in Postgres
 * (migration 20260928120000), so no service-role key exists anywhere in this
 * path — the route acts as the signed-in user and can only ever delete them.
 *
 * Order matters. Tokens are revoked first, because once the auth.users row is
 * gone the platform_accounts rows have cascaded away and we no longer know what
 * to revoke. Revocation failures do not stop the delete: REQ005 says "at any
 * time", and a provider outage must not trap someone in an account they want
 * gone.
 */

export const runtime = "nodejs";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export async function POST(request: Request) {
  if (!url || !anonKey) {
    console.error("[account] delete route missing Supabase env");
    return json(500, { error: "Server is not configured for account deletion." });
  }

  const token = bearerToken(request.headers.get("authorization"));
  if (!token) {
    return json(401, { error: "Sign in again to delete your account." });
  }

  // The caller's JWT, not a privileged key. Every query below is still subject
  // to RLS, and auth.uid() inside the RPC resolves to this user.
  const supabase = createClient(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: { headers: { Authorization: `Bearer ${token}` } },
  });

  const { data: userData, error: userError } = await supabase.auth.getUser();
  if (userError || !userData.user) {
    return json(401, { error: "Your session has expired. Sign in and try again." });
  }

  // Read before deleting: this is the last moment these rows exist.
  const { data: accounts, error: accountsError } = await supabase
    .from("platform_accounts")
    .select("platform, access_token");

  if (accountsError) {
    console.error("[account] could not read platform accounts", {
      message: accountsError.message,
    });
    return json(500, { error: "We couldn't start deletion. Try again in a moment." });
  }

  const revocations = await revokePlatformTokens(
    (accounts ?? []) as PlatformAccount[],
  );

  const { error: deleteError } = await supabase.rpc("delete_my_account");

  if (deleteError) {
    console.error("[account] delete_my_account failed", {
      message: deleteError.message,
      code: deleteError.code,
    });
    return json(500, {
      error: "We couldn't delete your account. Nothing was removed — try again.",
    });
  }

  // The JWT the caller still holds is now orphaned: it stays cryptographically
  // valid until it expires, but every table it could reach is empty and the
  // refresh token died with the user row. The client signs out immediately on
  // receiving this.
  return json(200, { deleted: true, revocations });
}

function bearerToken(header: string | null): string | null {
  if (!header) return null;
  const match = /^Bearer\s+(.+)$/i.exec(header.trim());
  return match ? match[1] : null;
}

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

import type { XboxErrorReason, XboxIdentity } from "@/lib/auth/xbox";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Writes the platform_accounts row for a verified Xbox identity. REQ014 · TM11-53 (AC1).
 *
 * Runs inside POST /api/xbox/link with a Supabase client built from the caller's own JWT,
 * the same way /api/account/delete does: no service-role key, so RLS
 * (platform_accounts_own) guarantees a user can only ever write their own row.
 *
 * Keys, from supabase/migrations/20260915120200_create_core_tables.sql:
 *   unique (user_id, platform)          one Xbox account per GameGPT user: re-linking
 *                                       replaces it (the upsert target below)
 *   unique (platform, platform_user_id) one GameGPT user per Xbox account: a second user
 *                                       trying to link the same XUID gets "taken"
 *
 * No Microsoft or Xbox token is stored. Linking only needs the XUID; reading the library
 * (TM11-56) will need a refresh token, and storing that is a separate decision recorded in
 * the ADR.
 */

/** The slice of supabase-js this needs, so tests can pass a fake. */
export type LinkDb = {
  auth: {
    getUser(): Promise<{ data: { user: { id: string } | null }; error: unknown }>;
  };
  from(table: "platform_accounts"): {
    upsert(
      row: Record<string, unknown>,
      opts: { onConflict: string },
    ): PromiseLike<{ error: { code?: string; message?: string } | null }>;
  };
};

export type LinkOutcome =
  | { status: "linked"; gamertag: string }
  | { status: "error"; reason: XboxErrorReason | "session"; httpStatus: number };

const UNIQUE_VIOLATION = "23505";

export async function persistXboxLink(
  db: LinkDb,
  identity: XboxIdentity,
  now: Date = new Date(),
): Promise<LinkOutcome> {
  const { data, error: userError } = await db.auth.getUser();
  if (userError || !data.user) {
    return { status: "error", reason: "session", httpStatus: 401 };
  }

  const { error } = await db.from("platform_accounts").upsert(
    {
      user_id: data.user.id,
      platform: "XBOX",
      platform_user_id: identity.xuid,
      import_method: "OAUTH",
      linked_at: now.toISOString(),
    },
    { onConflict: "user_id,platform" },
  );

  if (error) {
    // The (user_id, platform) conflict is handled by the upsert, so a unique violation
    // here can only be (platform, platform_user_id): someone else already owns this XUID.
    if (error.code === UNIQUE_VIOLATION) {
      return { status: "error", reason: "taken", httpStatus: 409 };
    }
    console.error("[xbox] platform_accounts upsert failed", {
      code: error.code,
      message: error.message,
    });
    return { status: "error", reason: "auth", httpStatus: 500 };
  }

  return { status: "linked", gamertag: identity.gamertag };
}

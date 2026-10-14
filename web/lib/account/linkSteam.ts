import type { LinkDb } from "@/lib/account/linkXbox";
import type { SteamErrorReason } from "@/lib/auth/steam";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Writes the platform_accounts row for a verified steamID64. TM11-52 (AC2, AC3).
 *
 * Same shape as persistXboxLink (TM11-53): runs inside POST /api/steam/link with a
 * Supabase client built from the caller's own JWT, so RLS (platform_accounts_own) limits
 * the write to their own row. Before this, a Steam link lived only in the browser's mock
 * store, so it vanished on another device and was invented for users who never linked.
 *
 *   unique (user_id, platform)          one Steam account per user: re-linking replaces it
 *   unique (platform, platform_user_id) one user per Steam account: a second user gets
 *                                       "taken"
 *
 * No Steam token exists to store: OpenID only proves who signed in.
 */

export type SteamLinkOutcome =
  | { status: "linked"; steamId: string }
  | { status: "error"; reason: SteamErrorReason; httpStatus: number };

const UNIQUE_VIOLATION = "23505";

export async function persistSteamLink(
  db: LinkDb,
  steamId: string,
  now: Date = new Date(),
): Promise<SteamLinkOutcome> {
  const { data, error: userError } = await db.auth.getUser();
  if (userError || !data.user) {
    return { status: "error", reason: "session", httpStatus: 401 };
  }

  const { error } = await db.from("platform_accounts").upsert(
    {
      user_id: data.user.id,
      platform: "STEAM",
      platform_user_id: steamId,
      import_method: "OAUTH",
      linked_at: now.toISOString(),
    },
    { onConflict: "user_id,platform" },
  );

  if (error) {
    // (user_id, platform) is the upsert target, so a unique violation can only be
    // (platform, platform_user_id): someone else already owns this Steam account.
    if (error.code === UNIQUE_VIOLATION) {
      return { status: "error", reason: "taken", httpStatus: 409 };
    }
    console.error("[steam] platform_accounts upsert failed", {
      code: error.code,
      message: error.message,
    });
    return { status: "error", reason: "save", httpStatus: 500 };
  }

  return { status: "linked", steamId };
}

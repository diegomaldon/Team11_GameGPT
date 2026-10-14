import type { Platform } from "@/lib/mock/data";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Linked accounts, read from and written to platform_accounts. REQ003 · TM11-52.
 *
 * The settings page used to show the mock store's idea of what was linked, which gave
 * every new user a connected Steam account and forgot real links on another device. This
 * reads the user's platform_accounts rows instead, so the page is right after a refresh and
 * when nothing is linked (AC3).
 *
 * Runs in the browser with the user's own session: RLS (platform_accounts_own) limits every
 * read and write to their rows. The user_id filters below are belt and braces on top.
 *
 * Supported is what public.platform_type allows (STEAM, XBOX, EPIC). PlayStation is listed
 * so users can see it is coming, but has no enum value, so it can't be linked.
 */

export type DbPlatform = "STEAM" | "XBOX" | "EPIC";

/** How Connect works for a platform: a sign-in redirect, a typed name, or not at all. */
export type ConnectVia = "steam" | "xbox" | "manual" | null;

export type LinkedAccount = {
  platform: Platform;
  connectVia: ConnectVia;
  connected: boolean;
  /** steamID64, XUID or the typed account name. */
  accountId: string | null;
  linkedAt: string | null;
  lastSyncedAt: string | null;
};

export type PlatformAccountRow = {
  platform: string;
  platform_user_id: string;
  linked_at: string | null;
  last_synced_at: string | null;
};

/** Page order, and how each platform maps to the database. */
export const ACCOUNT_PLATFORMS: { platform: Platform; db: DbPlatform | null; via: ConnectVia }[] =
  [
    { platform: "steam", db: "STEAM", via: "steam" },
    { platform: "xbox", db: "XBOX", via: "xbox" },
    { platform: "epic", db: "EPIC", via: "manual" },
    { platform: "playstation", db: null, via: null },
  ];

export const ACCOUNT_COLUMNS = "platform, platform_user_id, linked_at, last_synced_at";

/** One row per listed platform, connected only where the user has a platform_accounts row. */
export function toLinkedAccounts(rows: PlatformAccountRow[]): LinkedAccount[] {
  const byPlatform = new Map(rows.map((r) => [r.platform.toUpperCase(), r]));
  return ACCOUNT_PLATFORMS.map(({ platform, db, via }) => {
    const row = db ? byPlatform.get(db) : undefined;
    return {
      platform,
      connectVia: via,
      connected: row !== undefined,
      accountId: row?.platform_user_id ?? null,
      linkedAt: row?.linked_at ?? null,
      lastSyncedAt: row?.last_synced_at ?? null,
    };
  });
}

export function dbPlatformFor(platform: Platform): DbPlatform | null {
  return ACCOUNT_PLATFORMS.find((p) => p.platform === platform)?.db ?? null;
}

// ---------------------------------------------------------------------------
// Database calls
// ---------------------------------------------------------------------------

type DbError = { code?: string; message?: string } | null;
type DbResult<T> = PromiseLike<{ data: T | null; error: DbError }>;
type Filtered = DbResult<unknown> & { eq(column: string, value: string): Filtered };

/** The slice of supabase-js this needs, so tests can pass a fake. */
export type AccountsDb = {
  from(table: "platform_accounts"): {
    select(columns: string): DbResult<PlatformAccountRow[]>;
    insert(row: Record<string, unknown>): DbResult<unknown>;
    update(patch: Record<string, unknown>): Filtered;
    delete(): Filtered;
  };
};

export class AccountsError extends Error {
  constructor(
    readonly reason: "load" | "save" | "taken" | "invalid" | "unsupported",
    message: string,
  ) {
    super(message);
  }
}

const UNIQUE_VIOLATION = "23505";

export async function loadLinkedAccounts(db: AccountsDb): Promise<LinkedAccount[]> {
  const { data, error } = await db.from("platform_accounts").select(ACCOUNT_COLUMNS);
  if (error) {
    throw new AccountsError("load", "Couldn't load your linked accounts.");
  }
  return toLinkedAccounts(data ?? []);
}

/**
 * Deletes the platform_accounts row. owned_games rows imported through it go too
 * (on delete cascade), which is why the page confirms first.
 */
export async function disconnectPlatform(
  db: AccountsDb,
  userId: string,
  platform: Platform,
): Promise<void> {
  const dbPlatform = requireSupported(platform);
  const { error } = await db
    .from("platform_accounts")
    .delete()
    .eq("user_id", userId)
    .eq("platform", dbPlatform);
  if (error) {
    throw new AccountsError("save", "Couldn't disconnect. Try again in a moment.");
  }
}

/** Account names Epic accepts are 3–16 characters; allow some slack for older ones. */
const MANUAL_NAME_PATTERN = /^[\p{L}\p{N} ._-]{3,32}$/u;

/**
 * Links a platform with no sign-in flow (Epic) by the account name the user types.
 * Unverified, so it is recorded as import_method MANUAL.
 */
export async function linkManualPlatform(
  db: AccountsDb,
  userId: string,
  platform: Platform,
  accountName: string,
  now: Date = new Date(),
): Promise<void> {
  const dbPlatform = requireSupported(platform);
  const name = accountName.trim();
  if (!MANUAL_NAME_PATTERN.test(name)) {
    throw new AccountsError(
      "invalid",
      "Enter your account name: 3 to 32 letters, numbers, spaces, dots, dashes or underscores.",
    );
  }
  const { error } = await db.from("platform_accounts").insert({
    user_id: userId,
    platform: dbPlatform,
    platform_user_id: name,
    import_method: "MANUAL",
    linked_at: now.toISOString(),
  });
  if (error?.code === UNIQUE_VIOLATION) {
    throw new AccountsError("taken", "That account is already linked to a GameGPT account.");
  }
  if (error) {
    throw new AccountsError("save", "Couldn't connect. Try again in a moment.");
  }
}

/** Stamps last_synced_at after a library import finishes. */
export async function markSynced(
  db: AccountsDb,
  userId: string,
  platform: Platform,
  now: Date = new Date(),
): Promise<void> {
  const dbPlatform = requireSupported(platform);
  const { error } = await db
    .from("platform_accounts")
    .update({ last_synced_at: now.toISOString() })
    .eq("user_id", userId)
    .eq("platform", dbPlatform);
  if (error) {
    throw new AccountsError("save", "Couldn't record the sync time.");
  }
}

function requireSupported(platform: Platform): DbPlatform {
  const dbPlatform = dbPlatformFor(platform);
  if (!dbPlatform) {
    throw new AccountsError("unsupported", "That platform can't be linked yet.");
  }
  return dbPlatform;
}

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------

const DATE_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

/**
 * "Never synced", "Synced just now", "Synced 5 min ago", "Synced 3 h ago", or the date
 * ("Synced Oct 2, 2026") once it is a day old.
 */
export function formatLastSynced(iso: string | null, now: Date = new Date()): string {
  if (!iso) {
    return "Never synced";
  }
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) {
    return "Never synced";
  }
  const minutes = Math.floor((now.getTime() - at.getTime()) / 60_000);
  if (minutes < 1) {
    return "Synced just now";
  }
  if (minutes < 60) {
    return `Synced ${minutes} min ago`;
  }
  if (minutes < 24 * 60) {
    return `Synced ${Math.floor(minutes / 60)} h ago`;
  }
  return `Synced ${DATE_FORMAT.format(at)}`;
}

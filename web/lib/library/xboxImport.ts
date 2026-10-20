import { XboxLinkError, type XboxErrorReason, type XboxSession } from "@/lib/auth/xbox";
import type { XboxImportSummary } from "@/lib/auth/xboxMessages";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Xbox library import, server half. REQ014 · TM11-56. Runs inside POST /api/xbox/import.
 *
 *   1. Check the Xbox session belongs to this user: their platform_accounts XBOX row must
 *      hold the same XUID, read with their own JWT so RLS scopes it to them.
 *   2. Read their title history from titlehub with the session's XSTS token.
 *   3. Hand the games to the GameGPT API (POST /api/library/xbox), which matches them to
 *      the catalogue and writes owned_games idempotently.
 *
 * "Owned" here means the title history: every game the account has played. Xbox has no
 * public purchase-history API for third-party apps, so a game bought but never launched
 * is not imported. docs/auth-xbox.md → "Importing the library".
 *
 * No token is stored. The XSTS token arrives in a 5-minute sealed cookie, is used for the
 * one titlehub call, and is dropped.
 */

export const TITLEHUB_URL = "https://titlehub.xboxlive.com";

export type XboxTitle = { title_id: string; name: string };

export function titleHistoryUrl(xuid: string): string {
  return `${TITLEHUB_URL}/users/xuid(${xuid})/titles/titlehistory/decoration/detail`;
}

/**
 * The account's played games, apps left out. Throws XboxLinkError:
 *   401 -> expired (the XSTS token lapsed), 403 -> private (privacy settings hide
 *   the history), 5xx or unreachable -> network, anything else -> import.
 */
export async function fetchXboxTitleHistory(
  session: XboxSession,
  fetchImpl: typeof fetch = fetch,
): Promise<XboxTitle[]> {
  let res: Response;
  try {
    res = await fetchImpl(titleHistoryUrl(session.xuid), {
      headers: {
        Authorization: `XBL3.0 x=${session.uhs};${session.xstsToken}`,
        "x-xbl-contract-version": "2",
        Accept: "application/json",
        "Accept-Language": "en-US",
      },
    });
  } catch {
    throw new XboxLinkError("network");
  }
  if (res.status === 401) throw new XboxLinkError("expired");
  if (res.status === 403) throw new XboxLinkError("private");
  if (res.status >= 500) throw new XboxLinkError("network");
  if (!res.ok) throw new XboxLinkError("import");

  const body = (await res.json().catch(() => null)) as { titles?: unknown } | null;
  if (!body || !Array.isArray(body.titles)) throw new XboxLinkError("import");

  const titles: XboxTitle[] = [];
  for (const t of body.titles as { titleId?: unknown; name?: unknown; type?: unknown }[]) {
    // Apps (Netflix, the Xbox app itself) share the history with games.
    if (t?.type !== "Game") continue;
    const titleId = typeof t.titleId === "string" ? t.titleId : String(t.titleId ?? "");
    const name = typeof t.name === "string" ? t.name.trim() : "";
    if (!/^\d{1,32}$/.test(titleId) || !name) continue;
    titles.push({ title_id: titleId, name: name.slice(0, 300) });
  }
  return titles;
}

/** The slice of supabase-js this needs, so tests can pass a fake. */
export type ImportDb = {
  auth: {
    getUser(): Promise<{ data: { user: { id: string } | null }; error: unknown }>;
  };
  from(table: "platform_accounts"): {
    select(columns: "platform_user_id"): {
      eq(column: "platform", value: "XBOX"): {
        maybeSingle(): PromiseLike<{
          data: { platform_user_id: string } | null;
          error: { message?: string } | null;
        }>;
      };
    };
  };
};

export type ImportOutcome =
  | { status: "imported"; summary: XboxImportSummary }
  | { status: "error"; reason: XboxErrorReason | "session"; httpStatus: number };

const ERROR_STATUS: Partial<Record<XboxErrorReason, number>> = {
  expired: 401,
  private: 403,
  network: 503,
};

export async function importXboxLibrary({
  db,
  session,
  apiUrl,
  fetchImpl = fetch,
}: {
  db: ImportDb;
  session: XboxSession;
  apiUrl: string;
  fetchImpl?: typeof fetch;
}): Promise<ImportOutcome> {
  const { data: auth, error: userError } = await db.auth.getUser();
  if (userError || !auth.user) {
    return { status: "error", reason: "session", httpStatus: 401 };
  }

  const { data: linked, error: readError } = await db
    .from("platform_accounts")
    .select("platform_user_id")
    .eq("platform", "XBOX")
    .maybeSingle();
  if (readError) {
    console.error("[xbox] platform_accounts read failed", { message: readError.message });
    return { status: "error", reason: "import", httpStatus: 500 };
  }
  if (!linked) return { status: "error", reason: "not_linked", httpStatus: 409 };
  // Without this, anyone could sign in to their own Xbox account and import its games
  // into a GameGPT account that has a different Xbox account linked.
  if (linked.platform_user_id !== session.xuid) {
    return { status: "error", reason: "mismatch", httpStatus: 409 };
  }

  let titles: XboxTitle[];
  try {
    titles = await fetchXboxTitleHistory(session, fetchImpl);
  } catch (err) {
    const reason = err instanceof XboxLinkError ? err.reason : "import";
    return { status: "error", reason, httpStatus: ERROR_STATUS[reason] ?? 502 };
  }

  let res: Response;
  try {
    res = await fetchImpl(`${apiUrl.replace(/\/$/, "")}/api/library/xbox`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ titles }),
    });
  } catch {
    return { status: "error", reason: "import", httpStatus: 502 };
  }
  const summary = (await res.json().catch(() => null)) as XboxImportSummary | null;
  if (!res.ok || !summary || typeof summary.total !== "number") {
    console.error("[xbox] library import rejected by the API", { status: res.status });
    return { status: "error", reason: "import", httpStatus: 502 };
  }
  return { status: "imported", summary };
}

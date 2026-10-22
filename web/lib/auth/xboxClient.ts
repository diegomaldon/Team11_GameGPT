import { getAccessToken } from "./token";
import type { XboxImportSummary } from "./xboxMessages";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Browser half of Xbox linking. REQ014 · TM11-53.
 *
 * After /api/xbox/callback verifies the Xbox identity it redirects to
 * /settings?xbox=verified. The page then calls this, which asks the server to attach the
 * identity it sealed in an httpOnly cookie to the signed-in user. The XUID never travels
 * through the URL or this code.
 */

export type XboxLinkResult =
  | { status: "linked"; gamertag: string }
  | { status: "error"; reason: string };

export async function completeXboxLink(
  fetchImpl: typeof fetch = fetch,
  token: string | null = getAccessToken(),
): Promise<XboxLinkResult> {
  if (!token) return { status: "error", reason: "session" };
  try {
    const res = await fetchImpl("/api/xbox/link", {
      method: "POST",
      credentials: "same-origin",
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = (await res.json().catch(() => ({}))) as {
      gamertag?: unknown;
      reason?: unknown;
    };
    if (res.ok && typeof body.gamertag === "string") {
      return { status: "linked", gamertag: body.gamertag };
    }
    return {
      status: "error",
      reason: typeof body.reason === "string" ? body.reason : "auth",
    };
  } catch {
    return { status: "error", reason: "network" };
  }
}

export type XboxImportResult =
  | { status: "imported"; summary: XboxImportSummary }
  | { status: "error"; reason: string };

/**
 * TM11-56. After /api/xbox/callback redirects to /settings?xbox=import-ready, the page calls
 * this to run the import with the Xbox session the server sealed in an httpOnly cookie.
 */
export async function completeXboxImport(
  fetchImpl: typeof fetch = fetch,
  token: string | null = getAccessToken(),
): Promise<XboxImportResult> {
  if (!token) return { status: "error", reason: "session" };
  try {
    const res = await fetchImpl("/api/xbox/import", {
      method: "POST",
      credentials: "same-origin",
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = (await res.json().catch(() => ({}))) as Partial<XboxImportSummary> & {
      reason?: unknown;
    };
    if (res.ok && typeof body.total === "number") {
      return { status: "imported", summary: body as XboxImportSummary };
    }
    return {
      status: "error",
      reason: typeof body.reason === "string" ? body.reason : "import",
    };
  } catch {
    return { status: "error", reason: "network" };
  }
}

import { getAccessToken } from "./token";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Browser half of saving a Steam link. TM11-52.
 *
 * After /api/steam/callback verifies the Steam sign-in it redirects to
 * /settings?steam=verified. The page then calls this, which asks the server to attach the
 * steamID64 it sealed in an httpOnly cookie to the signed-in user. Same contract as
 * completeXboxLink in xboxClient.ts.
 */

export type SteamLinkResult =
  | { status: "linked"; steamId: string }
  | { status: "error"; reason: string };

export async function completeSteamLink(
  fetchImpl: typeof fetch = fetch,
  token: string | null = getAccessToken(),
): Promise<SteamLinkResult> {
  if (!token) {
    return { status: "error", reason: "session" };
  }
  try {
    const res = await fetchImpl("/api/steam/link", {
      method: "POST",
      credentials: "same-origin",
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = (await res.json().catch(() => ({}))) as {
      steamId?: unknown;
      reason?: unknown;
    };
    if (res.ok && typeof body.steamId === "string") {
      return { status: "linked", steamId: body.steamId };
    }
    return {
      status: "error",
      reason: typeof body.reason === "string" ? body.reason : "save",
    };
  } catch {
    return { status: "error", reason: "network" };
  }
}

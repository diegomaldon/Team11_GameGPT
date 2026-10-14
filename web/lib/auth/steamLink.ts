import { createHmac, timingSafeEqual } from "node:crypto";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Handing a verified steamID64 from /api/steam/callback to POST /api/steam/link. TM11-52.
 *
 * The callback knows which Steam account signed in, but not which GameGPT user is asking:
 * the Supabase session lives in the browser, not in a cookie. So, as with Xbox
 * (lib/auth/xbox.ts), the callback seals the steamID64 into a short-lived HMAC-signed
 * httpOnly cookie, and the settings page then calls POST /api/steam/link with its bearer
 * token. Putting the id in the URL instead would let anyone link any Steam account.
 *
 * Steam OpenID has no client secret to key the HMAC with, hence STEAM_LINK_SECRET.
 */

export const STEAM_LINK_COOKIE = "steam_link_identity";
export const STEAM_LINK_COOKIE_PATH = "/api/steam";
export const STEAM_LINK_TTL_SECONDS = 600;

/** Shorter than this and the HMAC key is guessable; 32 chars is `openssl rand -hex 16`. */
const MIN_SECRET_LENGTH = 32;

const STEAM_ID_PATTERN = /^\d{17}$/;

/** The server-only signing secret, or null when it is missing or too short to trust. */
export function steamLinkSecretFromEnv(env: NodeJS.ProcessEnv = process.env): string | null {
  const secret = env.STEAM_LINK_SECRET?.trim();
  return secret && secret.length >= MIN_SECRET_LENGTH ? secret : null;
}

function sign(payload: string, secret: string): string {
  const key = createHmac("sha256", secret).update("gamegpt:steam-link:v1").digest();
  return createHmac("sha256", key).update(payload).digest("base64url");
}

export function sealSteamId(steamId: string, secret: string, now: number = Date.now()): string {
  const payload = Buffer.from(
    JSON.stringify({ steamId, exp: now + STEAM_LINK_TTL_SECONDS * 1000 }),
  ).toString("base64url");
  return `${payload}.${sign(payload, secret)}`;
}

/** Returns the steamID64 only if the signature matches and it has not expired. */
export function openSteamId(
  sealed: string | undefined | null,
  secret: string,
  now: number = Date.now(),
): string | null {
  if (!sealed) {
    return null;
  }
  const [payload, sig] = sealed.split(".");
  if (!payload || !sig) {
    return null;
  }
  const a = Buffer.from(sig);
  const b = Buffer.from(sign(payload, secret));
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return null;
  }
  try {
    const data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as {
      steamId?: unknown;
      exp?: unknown;
    };
    if (typeof data.exp !== "number" || data.exp < now) {
      return null;
    }
    if (typeof data.steamId !== "string" || !STEAM_ID_PATTERN.test(data.steamId)) {
      return null;
    }
    return data.steamId;
  } catch {
    return null;
  }
}

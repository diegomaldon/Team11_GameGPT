import {
  createCipheriv,
  createDecipheriv,
  createHash,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";
import type { XboxErrorReason } from "./xboxMessages";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Xbox account linking. REQ014 · TM11-53. Decision: docs/adr/0001-xbox-account-linking.md
 *
 * Xbox has no OpenID like Steam. Linking is three hops, all server-side:
 *
 *   1. Microsoft identity platform (consumer accounts), OAuth 2.0 authorization code + PKCE,
 *      scope XboxLive.signin. Gives a Microsoft access token.
 *   2. user.auth.xboxlive.com: trades that token for an Xbox Live user token.
 *   3. xsts.auth.xboxlive.com: trades the user token for an XSTS token whose claims carry the
 *      XUID and gamertag. This is also the hop that rejects accounts that cannot use Xbox
 *      Live (no profile, child account, region), each with its own XErr code (AC2).
 *
 * Every rule here is a pure function or takes an injected fetch, so the flow is unit-tested
 * without a browser, a Microsoft account, or the network.
 *
 * Server-only (node:crypto). Messages and result URLs live in ./xboxMessages so the
 * Settings page can import them without pulling crypto into the browser bundle.
 */

export {
  describeXboxErrorReason,
  describeXboxResult,
  xboxLinkedAccountsResult,
} from "./xboxMessages";
export type { XboxErrorReason } from "./xboxMessages";

export const MS_AUTHORIZE_URL =
  "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize";
export const MS_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token";
export const XBL_USER_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate";
export const XBL_XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize";

/** XboxLive.signin is the scope the Xbox Live user-token exchange accepts. */
export const XBOX_SCOPE = "XboxLive.signin";

/** Cookies set by /api/xbox/login and read by /api/xbox/callback. */
export const XBOX_STATE_COOKIE = "xbox_oauth_state";
export const XBOX_VERIFIER_COOKIE = "xbox_oauth_verifier";
/** Set by /api/xbox/callback, consumed once by POST /api/xbox/link. */
export const XBOX_LINK_COOKIE = "xbox_link_identity";
export const XBOX_LINK_TTL_SECONDS = 600;
/** Set by /api/xbox/login?intent=import, read by the callback. TM11-56. */
export const XBOX_INTENT_COOKIE = "xbox_oauth_intent";
/** Set by /api/xbox/callback on an import, consumed once by POST /api/xbox/import. */
export const XBOX_IMPORT_COOKIE = "xbox_import_session";
/** Short: the cookie holds a live XSTS token, and the page uses it straight away. */
export const XBOX_IMPORT_TTL_SECONDS = 300;

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export type XboxConfig = { clientId: string; clientSecret: string };

/** Null when the server has no Azure app registration configured. */
export function xboxConfigFromEnv(env: NodeJS.ProcessEnv = process.env): XboxConfig | null {
  const clientId = env.XBOX_CLIENT_ID?.trim();
  const clientSecret = env.XBOX_CLIENT_SECRET?.trim();
  return clientId && clientSecret ? { clientId, clientSecret } : null;
}

// ---------------------------------------------------------------------------
// Leaving: PKCE + authorize URL
// ---------------------------------------------------------------------------

function base64url(buf: Buffer): string {
  return buf.toString("base64url");
}

/** RFC 7636 verifier: 43+ chars from the unreserved set. */
export function createCodeVerifier(): string {
  return base64url(randomBytes(32));
}

/** S256 challenge for a verifier. */
export function codeChallengeFor(verifier: string): string {
  return base64url(createHash("sha256").update(verifier).digest());
}

export function buildXboxAuthUrl({
  clientId,
  redirectUri,
  state,
  codeChallenge,
}: {
  clientId: string;
  redirectUri: string;
  state: string;
  codeChallenge: string;
}): string {
  const url = new URL(MS_AUTHORIZE_URL);
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("redirect_uri", redirectUri);
  url.searchParams.set("response_mode", "query");
  url.searchParams.set("scope", XBOX_SCOPE);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  // Always show the account picker, so a user signed in to the wrong Microsoft account
  // can switch instead of silently linking it.
  url.searchParams.set("prompt", "select_account");
  return url.toString();
}

// ---------------------------------------------------------------------------
// Coming back
// ---------------------------------------------------------------------------

export type XboxCallback =
  | { status: "code"; code: string }
  | { status: "cancelled" }
  | { status: "error"; reason: XboxErrorReason };

/**
 * Reads what Microsoft sent to /api/xbox/callback. The caller checks state first; this only
 * classifies. A user pressing "No" on the consent screen comes back as error=access_denied on
 * a normal page load, so it must be a cancel, not a failure (AC2).
 */
export function parseXboxCallback(params: URLSearchParams): XboxCallback {
  const error = params.get("error");
  if (error === "access_denied") return { status: "cancelled" };
  if (error) return { status: "error", reason: "auth" };
  const code = params.get("code");
  if (!code) return { status: "error", reason: "auth" };
  return { status: "code", code };
}

export class XboxLinkError extends Error {
  constructor(readonly reason: XboxErrorReason) {
    super(`xbox link failed: ${reason}`);
    this.name = "XboxLinkError";
  }
}

/**
 * XSTS XErr codes for accounts that can sign in to Microsoft but cannot use Xbox Live.
 * Values as returned in the 401 body of xsts/authorize.
 */
export const XSTS_ERRORS: Record<number, XboxErrorReason> = {
  2148916233: "no_profile",
  2148916235: "region",
  2148916236: "verification",
  2148916237: "verification",
  2148916238: "child",
};

export function reasonForXErr(xerr: unknown): XboxErrorReason {
  return typeof xerr === "number" && xerr in XSTS_ERRORS ? XSTS_ERRORS[xerr] : "unsupported";
}

export type XboxIdentity = { xuid: string; gamertag: string };

/**
 * An identity plus what titlehub needs to read the library: the user hash and the XSTS
 * token, sent as `XBL3.0 x=<uhs>;<token>`. Lives for one import, never stored. TM11-56.
 */
export type XboxSession = XboxIdentity & { uhs: string; xstsToken: string };

async function postJson(
  fetchImpl: typeof fetch,
  url: string,
  init: RequestInit,
): Promise<Response> {
  try {
    return await fetchImpl(url, init);
  } catch {
    throw new XboxLinkError("network");
  }
}

/** Hop 1: authorization code -> Microsoft access token. */
export async function exchangeCode(
  { code, verifier, redirectUri, config }: {
    code: string;
    verifier: string;
    redirectUri: string;
    config: XboxConfig;
  },
  fetchImpl: typeof fetch = fetch,
): Promise<string> {
  const body = new URLSearchParams({
    client_id: config.clientId,
    client_secret: config.clientSecret,
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri,
    code_verifier: verifier,
    scope: XBOX_SCOPE,
  });
  const res = await postJson(fetchImpl, MS_TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
  if (res.status >= 500) throw new XboxLinkError("network");
  const data = (await res.json().catch(() => ({}))) as { access_token?: unknown };
  if (!res.ok || typeof data.access_token !== "string") throw new XboxLinkError("auth");
  return data.access_token;
}

/**
 * Hops 2 and 3: Microsoft access token -> Xbox Live user token -> XSTS identity.
 * Throws XboxLinkError with a specific reason for every refusal.
 */
export async function getXboxIdentity(
  msAccessToken: string,
  fetchImpl: typeof fetch = fetch,
): Promise<XboxIdentity> {
  const { xuid, gamertag } = await getXboxSession(msAccessToken, fetchImpl);
  return { xuid, gamertag };
}

/** The same hops, keeping the XSTS token and user hash for a library import. TM11-56. */
export async function getXboxSession(
  msAccessToken: string,
  fetchImpl: typeof fetch = fetch,
): Promise<XboxSession> {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json",
    "x-xbl-contract-version": "1",
  };

  const userRes = await postJson(fetchImpl, XBL_USER_AUTH_URL, {
    method: "POST",
    headers,
    body: JSON.stringify({
      Properties: {
        AuthMethod: "RPS",
        SiteName: "user.auth.xboxlive.com",
        // "d=" because the token came from the v2.0 (MSAL-style) endpoint.
        RpsTicket: `d=${msAccessToken}`,
      },
      RelyingParty: "http://auth.xboxlive.com",
      TokenType: "JWT",
    }),
  });
  if (userRes.status >= 500) throw new XboxLinkError("network");
  const user = (await userRes.json().catch(() => ({}))) as { Token?: unknown };
  if (!userRes.ok || typeof user.Token !== "string") throw new XboxLinkError("auth");

  const xstsRes = await postJson(fetchImpl, XBL_XSTS_URL, {
    method: "POST",
    headers,
    body: JSON.stringify({
      Properties: { SandboxId: "RETAIL", UserTokens: [user.Token] },
      RelyingParty: "http://xboxlive.com",
      TokenType: "JWT",
    }),
  });
  if (xstsRes.status >= 500) throw new XboxLinkError("network");
  const xsts = (await xstsRes.json().catch(() => ({}))) as {
    XErr?: unknown;
    Token?: unknown;
    DisplayClaims?: { xui?: { xid?: unknown; gtg?: unknown; uhs?: unknown }[] };
  };
  if (xstsRes.status === 401) throw new XboxLinkError(reasonForXErr(xsts.XErr));
  if (!xstsRes.ok) throw new XboxLinkError("auth");

  const claims = xsts.DisplayClaims?.xui?.[0];
  const xuid = typeof claims?.xid === "string" ? claims.xid : "";
  const gamertag = typeof claims?.gtg === "string" ? claims.gtg : "";
  // A real XUID is a decimal integer. Anything else means we got the wrong relying party.
  if (!/^\d{1,20}$/.test(xuid) || !gamertag) throw new XboxLinkError("unsupported");
  const uhs = typeof claims?.uhs === "string" ? claims.uhs : "";
  const xstsToken = typeof xsts.Token === "string" ? xsts.Token : "";
  return { xuid, gamertag, uhs, xstsToken };
}

// ---------------------------------------------------------------------------
// Handing the verified identity to the signed-in user (callback -> /api/xbox/link)
// ---------------------------------------------------------------------------
//
// The callback knows the Xbox identity but not who the GameGPT user is: the Supabase
// session lives in the browser, not in a cookie. So the callback seals the identity into a
// short-lived HMAC-signed httpOnly cookie and the page then calls POST /api/xbox/link with
// its bearer token. Putting the XUID in the URL instead would let anyone link any XUID.

// Each cookie kind has its own key, so a link cookie can never be replayed as an import
// cookie or the other way round.
const LINK_PURPOSE = "gamegpt:xbox-link:v1";
const IMPORT_PURPOSE = "gamegpt:xbox-import:v1";

function purposeKey(config: XboxConfig, purpose: string): Buffer {
  return createHmac("sha256", config.clientSecret).update(purpose).digest();
}

function seal(data: object, ttlSeconds: number, key: Buffer, now: number): string {
  const payload = base64url(Buffer.from(JSON.stringify({ ...data, exp: now + ttlSeconds * 1000 })));
  const sig = base64url(createHmac("sha256", key).update(payload).digest());
  return `${payload}.${sig}`;
}

/** The payload, only if the signature matches and it has not expired. */
function unseal(
  sealed: string | undefined | null,
  key: Buffer,
  now: number,
): Record<string, unknown> | null {
  if (!sealed) return null;
  const [payload, sig] = sealed.split(".");
  if (!payload || !sig) return null;
  const expected = base64url(createHmac("sha256", key).update(payload).digest());
  const a = Buffer.from(sig);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
  try {
    const data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as Record<
      string,
      unknown
    >;
    if (typeof data.exp !== "number" || data.exp < now) return null;
    return data;
  } catch {
    return null;
  }
}

export function sealIdentity(
  identity: XboxIdentity,
  config: XboxConfig,
  now: number = Date.now(),
): string {
  // Pick the fields: a full XboxSession passed here must not put its XSTS token in the
  // link cookie.
  const { xuid, gamertag } = identity;
  return seal({ xuid, gamertag }, XBOX_LINK_TTL_SECONDS, purposeKey(config, LINK_PURPOSE), now);
}

/** Returns the identity only if the signature matches and it has not expired. */
export function openIdentity(
  sealed: string | undefined | null,
  config: XboxConfig,
  now: number = Date.now(),
): XboxIdentity | null {
  const data = unseal(sealed, purposeKey(config, LINK_PURPOSE), now);
  if (!data || typeof data.xuid !== "string" || typeof data.gamertag !== "string") return null;
  return { xuid: data.xuid, gamertag: data.gamertag };
}

// The import cookie carries a live XSTS token, a bearer credential that outlives the
// cookie, so it is encrypted, not just signed: AES-256-GCM, with the purpose as
// associated data. The link cookie above only holds an XUID and gamertag, which aren't
// secret, so signing is enough there.
const IMPORT_FORMAT = "v1";
const GCM_IV_BYTES = 12;

/**
 * Encrypts the short-lived Xbox session for POST /api/xbox/import. TM11-56. Without the
 * server's secret the cookie value reveals nothing, and any change to it fails to open.
 */
export function sealImportSession(
  session: XboxSession,
  config: XboxConfig,
  now: number = Date.now(),
): string {
  const { xuid, gamertag, uhs, xstsToken } = session;
  const plaintext = JSON.stringify({
    xuid, gamertag, uhs, xstsToken, exp: now + XBOX_IMPORT_TTL_SECONDS * 1000,
  });
  const iv = randomBytes(GCM_IV_BYTES);
  const cipher = createCipheriv("aes-256-gcm", purposeKey(config, IMPORT_PURPOSE), iv);
  cipher.setAAD(Buffer.from(IMPORT_PURPOSE));
  const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  return [IMPORT_FORMAT, iv, ciphertext, cipher.getAuthTag()]
    .map((part) => (typeof part === "string" ? part : base64url(part)))
    .join(".");
}

/** The session, only if it decrypts and authenticates under this server's key and has
 * not expired. */
function decryptImportSession(
  sealed: string | undefined | null,
  config: XboxConfig,
  now: number,
): Record<string, unknown> | null {
  if (!sealed) return null;
  const [format, iv, ciphertext, tag, ...rest] = sealed.split(".");
  if (format !== IMPORT_FORMAT || !iv || !ciphertext || !tag || rest.length) return null;
  try {
    const decipher = createDecipheriv(
      "aes-256-gcm",
      purposeKey(config, IMPORT_PURPOSE),
      Buffer.from(iv, "base64url"),
    );
    decipher.setAAD(Buffer.from(IMPORT_PURPOSE));
    decipher.setAuthTag(Buffer.from(tag, "base64url"));
    const plaintext = Buffer.concat([
      decipher.update(Buffer.from(ciphertext, "base64url")),
      decipher.final(), // throws if the tag doesn't match: wrong key or a changed byte
    ]).toString("utf8");
    const data = JSON.parse(plaintext) as Record<string, unknown>;
    if (typeof data.exp !== "number" || data.exp < now) return null;
    return data;
  } catch {
    return null;
  }
}

export function openImportSession(
  sealed: string | undefined | null,
  config: XboxConfig,
  now: number = Date.now(),
): XboxSession | null {
  const data = decryptImportSession(sealed, config, now);
  if (!data) return null;
  const { xuid, gamertag, uhs, xstsToken } = data;
  if (
    typeof xuid !== "string" ||
    typeof gamertag !== "string" ||
    typeof uhs !== "string" ||
    typeof xstsToken !== "string" ||
    !uhs ||
    !xstsToken
  ) {
    return null;
  }
  return { xuid, gamertag, uhs, xstsToken };
}

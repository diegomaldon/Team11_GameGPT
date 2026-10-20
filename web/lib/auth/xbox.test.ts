import { createHash } from "node:crypto";
import { describe, it, expect, vi } from "vitest";
import { describeXboxImport } from "./xboxMessages";
import {
  MS_AUTHORIZE_URL,
  MS_TOKEN_URL,
  XBL_USER_AUTH_URL,
  XBL_XSTS_URL,
  XboxLinkError,
  buildXboxAuthUrl,
  codeChallengeFor,
  createCodeVerifier,
  describeXboxResult,
  exchangeCode,
  getXboxIdentity,
  getXboxSession,
  openIdentity,
  openImportSession,
  parseXboxCallback,
  reasonForXErr,
  sealIdentity,
  sealImportSession,
  xboxConfigFromEnv,
  xboxLinkedAccountsResult,
} from "./xbox";

/**
 * TM11-53 — Link Xbox account. Grouped by acceptance criterion so the output reads as a
 * checklist. No network: every Microsoft / Xbox endpoint is a fake fetch.
 */

const CONFIG = { clientId: "client-123", clientSecret: "s3cret" };
const IDENTITY = { xuid: "2533274812345678", gamertag: "MajorNelson" };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Routes each Xbox / Microsoft URL to a canned response. */
function fakeFetch(routes: Record<string, () => Response | Promise<Response>>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const handler = routes[url];
    if (!handler) throw new Error(`unexpected fetch ${url}`);
    return handler();
  }) as unknown as typeof fetch;
}

const okUser = () => json(200, { Token: "user-token", DisplayClaims: { xui: [{ uhs: "1" }] } });
const okXsts = () =>
  json(200, {
    Token: "xsts-token",
    DisplayClaims: { xui: [{ uhs: "1", xid: IDENTITY.xuid, gtg: IDENTITY.gamertag }] },
  });

// ---------------------------------------------------------------------------
describe("AC1 — implements the chosen access path (Microsoft OAuth + Xbox Live XSTS)", () => {
  it("redirects to Microsoft's consumer endpoint with PKCE and the XboxLive.signin scope", () => {
    const url = new URL(
      buildXboxAuthUrl({
        clientId: "client-123",
        redirectUri: "https://app.example/api/xbox/callback",
        state: "nonce",
        codeChallenge: "challenge",
      }),
    );
    expect(`${url.origin}${url.pathname}`).toBe(MS_AUTHORIZE_URL);
    expect(url.searchParams.get("scope")).toBe("XboxLive.signin");
    expect(url.searchParams.get("response_type")).toBe("code");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("code_challenge")).toBe("challenge");
    expect(url.searchParams.get("redirect_uri")).toBe("https://app.example/api/xbox/callback");
    expect(url.searchParams.get("state")).toBe("nonce");
  });

  it("builds a valid S256 PKCE pair", () => {
    const verifier = createCodeVerifier();
    expect(verifier).toMatch(/^[A-Za-z0-9_-]{43,128}$/);
    // S256 = unpadded base64url of SHA-256(verifier), checked against an independent hash.
    const expected = createHash("sha256").update(verifier).digest("base64url");
    const challenge = codeChallengeFor(verifier);
    expect(challenge).toBe(expected);
    expect(challenge).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(codeChallengeFor(createCodeVerifier())).not.toBe(challenge);
  });

  it("exchanges the code with the verifier and secret, server-side", async () => {
    const fetchImpl = fakeFetch({ [MS_TOKEN_URL]: () => json(200, { access_token: "ms-at" }) });
    await expect(
      exchangeCode(
        { code: "c0de", verifier: "v", redirectUri: "https://a/cb", config: CONFIG },
        fetchImpl,
      ),
    ).resolves.toBe("ms-at");
    const body = new URLSearchParams(
      (vi.mocked(fetchImpl).mock.calls[0][1] as RequestInit).body as string,
    );
    expect(body.get("grant_type")).toBe("authorization_code");
    expect(body.get("code_verifier")).toBe("v");
    expect(body.get("client_secret")).toBe("s3cret");
  });

  it("turns the Microsoft token into an XUID and gamertag via user token + XSTS", async () => {
    const fetchImpl = fakeFetch({ [XBL_USER_AUTH_URL]: okUser, [XBL_XSTS_URL]: okXsts });
    await expect(getXboxIdentity("ms-at", fetchImpl)).resolves.toEqual(IDENTITY);
    const userBody = JSON.parse(
      (vi.mocked(fetchImpl).mock.calls[0][1] as RequestInit).body as string,
    );
    expect(userBody.Properties.RpsTicket).toBe("d=ms-at");
    const xstsBody = JSON.parse(
      (vi.mocked(fetchImpl).mock.calls[1][1] as RequestInit).body as string,
    );
    expect(xstsBody.Properties.UserTokens).toEqual(["user-token"]);
    expect(xstsBody.RelyingParty).toBe("http://xboxlive.com");
  });

  it("rejects an XSTS response without a numeric XUID", async () => {
    const fetchImpl = fakeFetch({
      [XBL_USER_AUTH_URL]: okUser,
      [XBL_XSTS_URL]: () => json(200, { DisplayClaims: { xui: [{ gtg: "x" }] } }),
    });
    await expect(getXboxIdentity("ms-at", fetchImpl)).rejects.toMatchObject({
      reason: "unsupported",
    });
  });

  it("seals the verified identity so only the server can read it back", () => {
    const sealed = sealIdentity(IDENTITY, CONFIG, 1_000);
    expect(sealed).not.toContain(IDENTITY.xuid);
    expect(openIdentity(sealed, CONFIG, 2_000)).toEqual(IDENTITY);
  });

  it("refuses a tampered, foreign-key or expired identity cookie", () => {
    const sealed = sealIdentity(IDENTITY, CONFIG, 1_000);
    const [payload, sig] = sealed.split(".");
    const forged = Buffer.from(
      JSON.stringify({ xuid: "1", gamertag: "evil", exp: 9e15 }),
    ).toString("base64url");
    expect(openIdentity(`${forged}.${sig}`, CONFIG, 2_000)).toBeNull();
    expect(openIdentity(sealed, { ...CONFIG, clientSecret: "other" }, 2_000)).toBeNull();
    expect(openIdentity(sealed, CONFIG, 1_000 + 601_000)).toBeNull();
    expect(openIdentity(`${payload}`, CONFIG, 2_000)).toBeNull();
    expect(openIdentity(undefined, CONFIG)).toBeNull();
  });

  it("reads config only when both id and secret are set", () => {
    expect(xboxConfigFromEnv({ XBOX_CLIENT_ID: "a", XBOX_CLIENT_SECRET: "b" } as never)).toEqual({
      clientId: "a",
      clientSecret: "b",
    });
    expect(xboxConfigFromEnv({ XBOX_CLIENT_ID: "a" } as never)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
describe("AC2 — auth failures and unsupported accounts get clear messages", () => {
  it("treats a declined consent as a cancel, not an error", () => {
    expect(parseXboxCallback(new URLSearchParams({ error: "access_denied" }))).toEqual({
      status: "cancelled",
    });
    expect(describeXboxResult("cancelled")?.tone).toBe("info");
  });

  it("maps other OAuth errors and a missing code to an auth failure", () => {
    expect(parseXboxCallback(new URLSearchParams({ error: "server_error" }))).toEqual({
      status: "error",
      reason: "auth",
    });
    expect(parseXboxCallback(new URLSearchParams())).toEqual({ status: "error", reason: "auth" });
    expect(parseXboxCallback(new URLSearchParams({ code: "abc" }))).toEqual({
      status: "code",
      code: "abc",
    });
  });

  it.each([
    [2148916233, "no_profile", /doesn't have an Xbox profile/],
    [2148916238, "child", /child account/],
    [2148916235, "region", /country or region/],
    [2148916236, "verification", /adult verification/],
    [2148916237, "verification", /adult verification/],
    [123, "unsupported", /can't be used with Xbox Live/],
  ])("XSTS XErr %d is reported as %s", async (xerr, reason, message) => {
    expect(reasonForXErr(xerr)).toBe(reason);
    const fetchImpl = fakeFetch({
      [XBL_USER_AUTH_URL]: okUser,
      [XBL_XSTS_URL]: () => json(401, { XErr: xerr }),
    });
    await expect(getXboxIdentity("ms-at", fetchImpl)).rejects.toMatchObject({ reason });
    expect(describeXboxResult("error", reason)?.message).toMatch(message);
  });

  it("reports a rejected code exchange as auth, and a 5xx or thrown fetch as network", async () => {
    const args = { code: "c", verifier: "v", redirectUri: "r", config: CONFIG };
    await expect(
      exchangeCode(args, fakeFetch({ [MS_TOKEN_URL]: () => json(400, { error: "invalid_grant" }) })),
    ).rejects.toMatchObject({ reason: "auth" });
    await expect(
      exchangeCode(args, fakeFetch({ [MS_TOKEN_URL]: () => json(503, {}) })),
    ).rejects.toMatchObject({ reason: "network" });
    await expect(
      exchangeCode(args, vi.fn().mockRejectedValue(new TypeError("offline")) as never),
    ).rejects.toBeInstanceOf(XboxLinkError);
  });

  it("has a specific, non-generic message for every failure reason", () => {
    const reasons = [
      "state", "auth", "no_profile", "child", "region", "verification",
      "unsupported", "network", "config", "taken", "expired", "session",
    ];
    const messages = reasons.map((r) => describeXboxResult("error", r)?.message);
    expect(new Set(messages).size).toBeGreaterThanOrEqual(reasons.length - 2); // state/expired share one
    expect(describeXboxResult("linked", null, "MajorNelson")?.message).toBe(
      "Xbox connected as MajorNelson.",
    );
  });

  it("always sends the user back to Settings, and never off-site", () => {
    expect(xboxLinkedAccountsResult("error", { reason: "child" })).toBe(
      "/settings?xbox=error&reason=child",
    );
    expect(xboxLinkedAccountsResult("verified", { next: "https://evil.example" })).toBe(
      "/settings?xbox=verified",
    );
  });
});

// ---------------------------------------------------------------------------
describe("TM11-56 — the short-lived session a library import needs", () => {
  const SESSION = { ...IDENTITY, uhs: "1", xstsToken: "xsts-token" };
  const xboxRoutes = () =>
    fakeFetch({ [XBL_USER_AUTH_URL]: okUser, [XBL_XSTS_URL]: okXsts });

  it("keeps the XSTS token and user hash titlehub needs", async () => {
    await expect(getXboxSession("ms-token", xboxRoutes())).resolves.toEqual(SESSION);
  });

  it("still gives linking only the XUID and gamertag", async () => {
    await expect(getXboxIdentity("ms-token", xboxRoutes())).resolves.toEqual(IDENTITY);
  });

  it("round-trips the import session and expires it after 5 minutes", () => {
    const now = 1_000_000;
    const sealed = sealImportSession(SESSION, CONFIG, now);
    expect(openImportSession(sealed, CONFIG, now + 299_000)).toEqual(SESSION);
    expect(openImportSession(sealed, CONFIG, now + 301_000)).toBeNull();
    expect(openImportSession(sealed, { ...CONFIG, clientSecret: "other" }, now)).toBeNull();
  });

  it("never accepts a link cookie as an import cookie, or the other way round", () => {
    const link = sealIdentity(IDENTITY, CONFIG);
    const importing = sealImportSession(SESSION, CONFIG);
    expect(openImportSession(link, CONFIG)).toBeNull();
    expect(openIdentity(importing, CONFIG)).toBeNull();
  });

  it("keeps the XSTS token out of the link cookie even if handed a full session", () => {
    const sealed = sealIdentity(SESSION, CONFIG);
    const payload = Buffer.from(sealed.split(".")[0], "base64url").toString("utf8");
    expect(payload).not.toContain("xsts-token");
    expect(openIdentity(sealed, CONFIG)).toEqual(IDENTITY);
  });

  it("fits a realistic XSTS token inside one cookie", () => {
    // Real XSTS tokens are around 1.5 KB; browsers cap a cookie at about 4 KB.
    const sealed = sealImportSession({ ...SESSION, xstsToken: "x".repeat(2000) }, CONFIG);
    expect(sealed.length).toBeLessThan(4000);
  });

  it("returns to Settings ready to import", () => {
    expect(xboxLinkedAccountsResult("import-ready")).toBe("/settings?xbox=import-ready");
  });

  it("describes new, repeat and empty imports", () => {
    const base = { total: 3, added: 3, updated: 0, already_owned: 0, matched: 2, unmatched: 1 };
    expect(describeXboxImport(base).message).toBe(
      "Imported 3 games from Xbox. 1 game didn't match our catalogue and is waiting for review.",
    );
    expect(describeXboxImport({ ...base, added: 0, updated: 3, unmatched: 0 }).message).toBe(
      "Your Xbox library is up to date: 3 games, none new.",
    );
    expect(describeXboxImport({ ...base, total: 0, added: 0 }).tone).toBe("info");
  });

  it("has its own message for each import failure", () => {
    const messages = ["not_linked", "mismatch", "private", "import"].map(
      (r) => describeXboxResult("error", r)?.message,
    );
    expect(new Set(messages).size).toBe(4);
    expect(messages).not.toContain(describeXboxResult("error", "auth")?.message);
  });
});

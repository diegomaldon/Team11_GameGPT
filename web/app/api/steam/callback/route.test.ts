import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { STEAM_OPENID_ENDPOINT } from "@/lib/auth/steam";
import { STEAM_LINK_COOKIE, openSteamId } from "@/lib/auth/steamLink";
import { GET } from "./route";

/**
 * TM11-52: after Steam confirms the sign-in, the callback seals the steamID64 in an httpOnly
 * cookie and redirects with steam=verified. The id never appears in the URL.
 */

vi.mock("@/lib/auth/steam", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/steam")>()),
  verifySteamAssertion: vi.fn().mockResolvedValue(true),
}));

const SECRET = "0123456789abcdef0123456789abcdef";
const STEAM_ID = "76561197960287930";
const CLAIMED = `https://steamcommunity.com/openid/id/${STEAM_ID}`;

function callback() {
  const params = new URLSearchParams({
    state: "nonce-123",
    "openid.ns": "http://specs.openid.net/auth/2.0",
    "openid.mode": "id_res",
    "openid.op_endpoint": STEAM_OPENID_ENDPOINT,
    "openid.claimed_id": CLAIMED,
    "openid.identity": CLAIMED,
    "openid.sig": "sig",
    "openid.signed": "signed,op_endpoint,claimed_id,identity,mode",
  });
  return new NextRequest(`http://localhost:3000/api/steam/callback?${params}`, {
    headers: { cookie: "steam_openid_state=nonce-123" },
  });
}

beforeEach(() => vi.stubEnv("STEAM_LINK_SECRET", SECRET));
afterEach(() => vi.unstubAllEnvs());

describe("GET /api/steam/callback", () => {
  it("redirects with steam=verified and seals the steamID64 in an httpOnly cookie", async () => {
    const res = await GET(callback());
    const location = res.headers.get("location")!;
    expect(new URL(location).search).toBe("?steam=verified");
    expect(location).not.toContain(STEAM_ID);

    const cookie = res.cookies.get(STEAM_LINK_COOKIE)!;
    expect(cookie.httpOnly).toBe(true);
    expect(cookie.path).toBe("/api/steam");
    expect(openSteamId(cookie.value, SECRET)).toBe(STEAM_ID);
  });

  it("reports missing configuration instead of linking without a secret", async () => {
    vi.stubEnv("STEAM_LINK_SECRET", "");
    const res = await GET(callback());
    expect(res.headers.get("location")).toContain("steam=error&reason=config");
    expect(res.cookies.get(STEAM_LINK_COOKIE)).toBeUndefined();
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { STEAM_LINK_COOKIE, sealSteamId } from "@/lib/auth/steamLink";
import { persistSteamLink } from "@/lib/account/linkSteam";
import { POST } from "./route";

/** TM11-52: POST /api/steam/link saves the sealed Steam sign-in for the signed-in user. */

vi.mock("@supabase/supabase-js", () => ({ createClient: vi.fn(() => ({})) }));
vi.mock("@/lib/account/linkSteam", () => ({ persistSteamLink: vi.fn() }));

const SECRET = "0123456789abcdef0123456789abcdef";
const STEAM_ID = "76561197960287930";

function link({ token = "jwt", cookie = sealSteamId(STEAM_ID, SECRET) } = {}) {
  const headers: Record<string, string> = {};
  if (token) {
    headers.authorization = `Bearer ${token}`;
  }
  if (cookie) {
    headers.cookie = `${STEAM_LINK_COOKIE}=${cookie}`;
  }
  return new NextRequest("http://localhost:3000/api/steam/link", { method: "POST", headers });
}

/** The single-use cookie is expired on every response. */
function expectCookieCleared(res: Response) {
  expect(res.headers.get("set-cookie")).toMatch(new RegExp(`${STEAM_LINK_COOKIE}=;`));
}

beforeEach(() => {
  vi.stubEnv("STEAM_LINK_SECRET", SECRET);
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://placeholder.supabase.co");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon");
  vi.mocked(persistSteamLink).mockResolvedValue({ status: "linked", steamId: STEAM_ID });
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("POST /api/steam/link", () => {
  it("saves the sealed steamID64 and returns it", async () => {
    const res = await POST(link());
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ steamId: STEAM_ID });
    expect(persistSteamLink).toHaveBeenCalledWith(expect.anything(), STEAM_ID);
    expectCookieCleared(res);
  });

  it("401s without a bearer token", async () => {
    const res = await POST(link({ token: "" }));
    expect(res.status).toBe(401);
    expect(persistSteamLink).not.toHaveBeenCalled();
    expectCookieCleared(res);
  });

  it("400s with a missing or forged cookie", async () => {
    for (const cookie of ["", "forged.value"]) {
      const res = await POST(link({ cookie }));
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ reason: "expired" });
    }
    expect(persistSteamLink).not.toHaveBeenCalled();
  });

  it("500s with reason config when the secret is not set", async () => {
    vi.stubEnv("STEAM_LINK_SECRET", "");
    const res = await POST(link());
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ reason: "config" });
  });

  it("passes a taken Steam account through as 409", async () => {
    vi.mocked(persistSteamLink).mockResolvedValue({
      status: "error",
      reason: "taken",
      httpStatus: 409,
    });
    const res = await POST(link());
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ reason: "taken" });
  });
});

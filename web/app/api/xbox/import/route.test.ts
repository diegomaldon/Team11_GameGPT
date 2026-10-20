import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { XBOX_IMPORT_COOKIE, sealIdentity, sealImportSession } from "@/lib/auth/xbox";
import { importXboxLibrary } from "@/lib/library/xboxImport";
import { POST } from "./route";

/** TM11-56: POST /api/xbox/import runs the import with the sealed Xbox session. */

vi.mock("@supabase/supabase-js", () => ({ createClient: vi.fn(() => ({})) }));
vi.mock("@/lib/library/xboxImport", () => ({ importXboxLibrary: vi.fn() }));

const CONFIG = { clientId: "client-123", clientSecret: "s3cret" };
const SESSION = {
  xuid: "2533274812345678", gamertag: "MajorNelson", uhs: "1", xstsToken: "xsts-token",
};
const SUMMARY = { total: 2, added: 2, updated: 0, already_owned: 0, matched: 2, unmatched: 0 };

function importRequest({ token = "jwt", cookie = sealImportSession(SESSION, CONFIG) } = {}) {
  const headers: Record<string, string> = {};
  if (token) {
    headers.authorization = `Bearer ${token}`;
  }
  if (cookie) {
    headers.cookie = `${XBOX_IMPORT_COOKIE}=${cookie}`;
  }
  return new NextRequest("http://localhost:3000/api/xbox/import", { method: "POST", headers });
}

function expectCookieCleared(res: Response) {
  expect(res.headers.get("set-cookie")).toMatch(new RegExp(`${XBOX_IMPORT_COOKIE}=;`));
}

beforeEach(() => {
  vi.stubEnv("XBOX_CLIENT_ID", CONFIG.clientId);
  vi.stubEnv("XBOX_CLIENT_SECRET", CONFIG.clientSecret);
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://placeholder.supabase.co");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon");
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://api.test");
  vi.mocked(importXboxLibrary).mockResolvedValue({ status: "imported", summary: SUMMARY } as never);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("POST /api/xbox/import", () => {
  it("imports with the sealed session and returns the summary", async () => {
    const res = await POST(importRequest());
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(SUMMARY);
    expect(importXboxLibrary).toHaveBeenCalledWith(
      expect.objectContaining({ session: SESSION, apiUrl: "http://api.test" }),
    );
    expectCookieCleared(res);
  });

  it("prefers API_URL for the server-to-server call", async () => {
    vi.stubEnv("API_URL", "http://api.internal:8000");
    await POST(importRequest());
    expect(importXboxLibrary).toHaveBeenCalledWith(
      expect.objectContaining({ apiUrl: "http://api.internal:8000" }),
    );
  });

  it("401s without a bearer token", async () => {
    const res = await POST(importRequest({ token: "" }));
    expect(res.status).toBe(401);
    expect(importXboxLibrary).not.toHaveBeenCalled();
    expectCookieCleared(res);
  });

  it("400s with a missing, forged or link-only cookie", async () => {
    for (const cookie of ["", "forged.value", sealIdentity(SESSION, CONFIG)]) {
      const res = await POST(importRequest({ cookie }));
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ reason: "expired" });
    }
    expect(importXboxLibrary).not.toHaveBeenCalled();
  });

  it("500s with reason config when no Azure app is set up", async () => {
    vi.stubEnv("XBOX_CLIENT_SECRET", "");
    const res = await POST(importRequest());
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ reason: "config" });
  });

  it("passes a refusal through with its status", async () => {
    vi.mocked(importXboxLibrary).mockResolvedValue({
      status: "error", reason: "mismatch", httpStatus: 409,
    });
    const res = await POST(importRequest());
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ reason: "mismatch" });
    expectCookieCleared(res);
  });
});

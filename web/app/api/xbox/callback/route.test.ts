import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import {
  XBOX_IMPORT_COOKIE,
  XBOX_INTENT_COOKIE,
  XBOX_LINK_COOKIE,
  XBOX_STATE_COOKIE,
  XBOX_VERIFIER_COOKIE,
} from "@/lib/auth/xbox";
import { GET } from "./route";

/** TM11-56: the callback seals an import session when the user came to import. */

vi.mock("@/lib/auth/xbox", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/xbox")>()),
  exchangeCode: vi.fn(async () => "ms-token"),
  getXboxSession: vi.fn(async () => ({
    xuid: "2533274812345678", gamertag: "MajorNelson", uhs: "1", xstsToken: "xsts-token",
  })),
}));

const STATE = "3f2b5c1e-0000-4000-8000-000000000000";

function callback(intent?: string) {
  const cookies = [`${XBOX_STATE_COOKIE}=${STATE}`, `${XBOX_VERIFIER_COOKIE}=verifier`];
  if (intent) {
    cookies.push(`${XBOX_INTENT_COOKIE}=${intent}`);
  }
  return GET(
    new NextRequest(`http://localhost:3000/api/xbox/callback?code=abc&state=${STATE}`, {
      headers: { cookie: cookies.join("; ") },
    }),
  );
}

const setCookies = (res: Response) => res.headers.getSetCookie().join("\n");

beforeEach(() => {
  vi.stubEnv("XBOX_CLIENT_ID", "client-123");
  vi.stubEnv("XBOX_CLIENT_SECRET", "s3cret");
});
afterEach(() => {
  vi.unstubAllEnvs();
});

describe("GET /api/xbox/callback", () => {
  it("returns import-ready with a 5-minute import cookie when the intent is import", async () => {
    const res = await callback("import");
    expect(res.headers.get("location")).toBe("http://localhost:3000/settings?xbox=import-ready");
    expect(setCookies(res)).toMatch(new RegExp(`${XBOX_IMPORT_COOKIE}=[^;]+;.*Max-Age=300`));
    expect(setCookies(res)).not.toMatch(new RegExp(`${XBOX_LINK_COOKIE}=[^;]`));
    expect(setCookies(res)).toMatch(new RegExp(`${XBOX_INTENT_COOKIE}=;`));
  });

  it("still links, with no import cookie, when there is no intent", async () => {
    const res = await callback();
    expect(res.headers.get("location")).toBe("http://localhost:3000/settings?xbox=verified");
    expect(setCookies(res)).toMatch(new RegExp(`${XBOX_LINK_COOKIE}=[^;]+`));
    expect(setCookies(res)).not.toMatch(new RegExp(`${XBOX_IMPORT_COOKIE}=[^;]`));
  });
});

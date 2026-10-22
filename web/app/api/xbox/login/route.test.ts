import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { XBOX_INTENT_COOKIE } from "@/lib/auth/xbox";
import { GET } from "./route";

/** TM11-56: /api/xbox/login remembers an import intent for the callback. */

beforeEach(() => {
  vi.stubEnv("XBOX_CLIENT_ID", "client-123");
  vi.stubEnv("XBOX_CLIENT_SECRET", "s3cret");
});
afterEach(() => {
  vi.unstubAllEnvs();
});

const login = (query: string) => GET(new NextRequest(`http://localhost:3000/api/xbox/login${query}`));

describe("GET /api/xbox/login", () => {
  it("sets the import intent cookie for ?intent=import", () => {
    const res = login("?next=/settings&intent=import");
    expect(res.headers.get("location")).toContain("login.microsoftonline.com");
    expect(res.headers.get("set-cookie")).toMatch(new RegExp(`${XBOX_INTENT_COOKIE}=import`));
  });

  it("clears any leftover intent for a plain link", () => {
    const res = login("?next=/settings");
    expect(res.headers.get("set-cookie")).toMatch(new RegExp(`${XBOX_INTENT_COOKIE}=;`));
  });
});

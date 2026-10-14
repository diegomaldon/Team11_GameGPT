import { describe, it, expect, vi } from "vitest";
import { persistXboxLink, type LinkDb } from "./linkXbox";

/** TM11-53 AC1 — the platform_accounts row written for a verified Xbox identity. */

const IDENTITY = { xuid: "2533274812345678", gamertag: "MajorNelson" };

function db(
  upsertError: { code?: string; message?: string } | null = null,
  user: { id: string } | null = { id: "user-1" },
) {
  const upsert = vi.fn().mockResolvedValue({ error: upsertError });
  const fake: LinkDb = {
    auth: { getUser: vi.fn().mockResolvedValue({ data: { user }, error: null }) },
    from: vi.fn(() => ({ upsert })),
  };
  return { fake, upsert };
}

describe("persistXboxLink", () => {
  it("writes a platform_accounts row with platform XBOX for the signed-in user", async () => {
    const { fake, upsert } = db();
    const now = new Date("2026-10-13T20:00:00Z");
    await expect(persistXboxLink(fake, IDENTITY, now)).resolves.toEqual({
      status: "linked",
      gamertag: "MajorNelson",
    });
    expect(fake.from).toHaveBeenCalledWith("platform_accounts");
    expect(upsert).toHaveBeenCalledWith(
      {
        user_id: "user-1",
        platform: "XBOX",
        platform_user_id: "2533274812345678",
        import_method: "OAUTH",
        linked_at: "2026-10-13T20:00:00.000Z",
      },
      { onConflict: "user_id,platform" },
    );
  });

  it("stores no Microsoft or Xbox token", async () => {
    const { fake, upsert } = db();
    await persistXboxLink(fake, IDENTITY);
    expect(upsert.mock.calls[0][0]).not.toHaveProperty("access_token");
  });

  it("reports an XUID already owned by another user as taken (409)", async () => {
    const { fake } = db({ code: "23505", message: "platform_accounts_platform_identity_key" });
    await expect(persistXboxLink(fake, IDENTITY)).resolves.toEqual({
      status: "error",
      reason: "taken",
      httpStatus: 409,
    });
  });

  it("requires a valid session (401) and never writes without one", async () => {
    const { fake, upsert } = db(null, null);
    await expect(persistXboxLink(fake, IDENTITY)).resolves.toMatchObject({
      reason: "session",
      httpStatus: 401,
    });
    expect(upsert).not.toHaveBeenCalled();
  });

  it("surfaces any other database error as a 500 without leaking it", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { fake } = db({ code: "42501", message: "permission denied" });
    await expect(persistXboxLink(fake, IDENTITY)).resolves.toEqual({
      status: "error",
      reason: "auth",
      httpStatus: 500,
    });
  });
});

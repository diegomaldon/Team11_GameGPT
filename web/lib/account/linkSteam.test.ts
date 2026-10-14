import { describe, expect, it, vi } from "vitest";
import type { LinkDb } from "./linkXbox";
import { persistSteamLink } from "./linkSteam";

/** TM11-52 AC2/AC3: a Steam link is saved to platform_accounts, so it survives a refresh. */

const STEAM_ID = "76561197960287930";

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

describe("persistSteamLink", () => {
  it("upserts a STEAM row for the signed-in user", async () => {
    const { fake, upsert } = db();
    const now = new Date("2026-10-13T20:00:00Z");
    await expect(persistSteamLink(fake, STEAM_ID, now)).resolves.toEqual({
      status: "linked",
      steamId: STEAM_ID,
    });
    expect(upsert).toHaveBeenCalledWith(
      {
        user_id: "user-1",
        platform: "STEAM",
        platform_user_id: STEAM_ID,
        import_method: "OAUTH",
        linked_at: "2026-10-13T20:00:00.000Z",
      },
      { onConflict: "user_id,platform" },
    );
  });

  it("reports a Steam account another user linked as taken (409)", async () => {
    const { fake } = db({ code: "23505" });
    await expect(persistSteamLink(fake, STEAM_ID)).resolves.toEqual({
      status: "error",
      reason: "taken",
      httpStatus: 409,
    });
  });

  it("requires a session (401) and never writes without one", async () => {
    const { fake, upsert } = db(null, null);
    await expect(persistSteamLink(fake, STEAM_ID)).resolves.toMatchObject({
      reason: "session",
      httpStatus: 401,
    });
    expect(upsert).not.toHaveBeenCalled();
  });

  it("reports any other write failure as save (500)", async () => {
    const { fake } = db({ code: "42501", message: "permission denied" });
    vi.spyOn(console, "error").mockImplementation(() => {});
    await expect(persistSteamLink(fake, STEAM_ID)).resolves.toMatchObject({
      reason: "save",
      httpStatus: 500,
    });
  });
});

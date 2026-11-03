// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest";
import { toLinkedAccounts, type PlatformAccountRow } from "@/lib/account/linkedAccounts";
import type { LibrarySyncJob } from "@/lib/api/types";
import {
  planRefresh,
  platformsToSync,
  savePending,
  steamProgress,
  takePending,
  XBOX_REFRESH_URL,
} from "./libraryRefresh";

/** TM11-60 (REQ006): what a manual library refresh re-syncs, and how. */

const STEAM_ID = "76561197960287930";

function accounts(...platforms: string[]) {
  const rows: PlatformAccountRow[] = platforms.map((platform) => ({
    platform,
    platform_user_id: platform === "STEAM" ? STEAM_ID : `${platform.toLowerCase()}-id`,
    linked_at: "2026-10-01T12:00:00Z",
    last_synced_at: null,
  }));
  return toLinkedAccounts(rows);
}

function job(patch: Partial<LibrarySyncJob>): LibrarySyncJob {
  return {
    job_id: "job-1",
    state: "importing",
    total: 0,
    processed: 0,
    synced: 0,
    failed: [],
    started_at: "2026-11-03T12:00:00Z",
    ...patch,
  } as LibrarySyncJob;
}

beforeEach(() => window.sessionStorage.clear());

describe("which linked platforms a refresh re-syncs", () => {
  it("syncs Steam by its steamID and Xbox through a sign-in", () => {
    const plan = planRefresh(accounts("STEAM", "XBOX"));

    expect(plan).toEqual({ steamId: STEAM_ID, xbox: true, epic: false });
    expect(platformsToSync(plan)).toEqual(["steam", "xbox"]);
  });

  it("has nothing to sync for Epic, which is added by hand or CSV", () => {
    const plan = planRefresh(accounts("EPIC"));

    expect(plan.epic).toBe(true);
    expect(platformsToSync(plan)).toEqual([]);
  });

  it("only syncs what is linked", () => {
    expect(platformsToSync(planRefresh(accounts("XBOX")))).toEqual(["xbox"]);
    expect(platformsToSync(planRefresh(accounts()))).toEqual([]);
  });

  it("brings the Xbox sign-in back to the Library as an import", () => {
    expect(XBOX_REFRESH_URL).toBe("/api/xbox/login?next=/library&intent=import");
  });
});

describe("the platforms still to sync survive the Xbox sign-in redirect", () => {
  it("are read back once", () => {
    savePending(["steam", "xbox"]);

    expect(takePending()).toEqual(["steam", "xbox"]);
    expect(takePending()).toBeNull();
  });

  it("ignores anything that isn't a platform list", () => {
    window.sessionStorage.setItem("gamegpt.libraryRefresh", '["steam","playstation",3]');
    expect(takePending()).toEqual(["steam"]);

    window.sessionStorage.setItem("gamegpt.libraryRefresh", "not json");
    expect(takePending()).toBeNull();
  });

  it("does nothing when storage is blocked", () => {
    const blocked = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });

    expect(() => savePending(["xbox"])).not.toThrow();
    expect(takePending()).toBeNull();
    blocked.mockRestore();
    vi.restoreAllMocks();
  });
});

describe("Steam progress while the refresh runs", () => {
  it("reads like the import it is", () => {
    expect(steamProgress(null)).toBe("Starting the Steam sync…");
    expect(steamProgress(job({ state: "fetching" }))).toBe("Fetching your Steam library…");
    expect(steamProgress(job({ state: "importing", processed: 3, total: 10 }))).toBe(
      "Importing 3 of 10 Steam games…",
    );
  });
});

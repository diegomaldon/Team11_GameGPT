// @vitest-environment jsdom

// TM11-60 (REQ006): the manual library refresh, against an in-memory platform_accounts.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { fakeAccountsDb, type StoredAccount } from "@/lib/account/fakeAccountsDb";
import type { AccountsDb } from "@/lib/account/linkedAccounts";
import { runLibrarySync } from "@/lib/api/client";
import type { LibrarySyncJob } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/session";
import { completeXboxImport, type XboxImportResult } from "@/lib/auth/xboxClient";
import { savePending, takePending, XBOX_REFRESH_URL } from "./libraryRefresh";
import { useLibraryRefresh } from "./useLibraryRefresh";

const current = vi.hoisted(() => ({ db: null as unknown as AccountsDb }));
vi.mock("@/lib/supabase", () => ({
  supabase: { from: (table: "platform_accounts") => current.db.from(table) },
}));
vi.mock("@/lib/auth/session", () => ({ useAuth: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ runLibrarySync: vi.fn() }));
vi.mock("@/lib/auth/xboxClient", () => ({ completeXboxImport: vi.fn() }));

const search = vi.hoisted(() => ({ params: new URLSearchParams() }));
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => search.params,
}));

const USER = "user-1";
const STEAM_ID = "76561197960287930";
const LINKED = { user_id: USER, linked_at: "2026-10-01T12:00:00Z", last_synced_at: null };
const STEAM: StoredAccount = { ...LINKED, platform: "STEAM", platform_user_id: STEAM_ID };
const XBOX: StoredAccount = { ...LINKED, platform: "XBOX", platform_user_id: "2533274812345678" };
const EPIC: StoredAccount = { ...LINKED, platform: "EPIC", platform_user_id: "epic-name" };

const SUMMARY = { total: 4, added: 2, updated: 2, already_owned: 0, matched: 4, unmatched: 0 };

function steamJob(state: LibrarySyncJob["state"], patch: Partial<LibrarySyncJob> = {}) {
  return {
    job_id: "job-1", state, total: 10, processed: 10, synced: 10, failed: [],
    started_at: "2026-11-03T12:00:00Z", ...patch,
  } as LibrarySyncJob;
}

/** A Steam sync the test finishes by hand, to look at the page while it runs. */
function heldSteamSync() {
  let finish: (job: LibrarySyncJob) => void = () => {};
  let report: (job: LibrarySyncJob) => void = () => {};
  vi.mocked(runLibrarySync).mockImplementation((_steamId, onUpdate) => {
    report = onUpdate;
    return new Promise((resolve) => (finish = resolve));
  });
  return {
    report: (job: LibrarySyncJob) => act(() => report(job)),
    finish: (job: LibrarySyncJob) => act(async () => finish(job)),
  };
}

function setup(seed: StoredAccount[]) {
  const fake = fakeAccountsDb(USER, seed);
  current.db = fake.db;
  vi.mocked(useAuth).mockReturnValue({
    status: "authenticated",
    user: { id: USER },
    session: { access_token: "jwt" },
  } as unknown as ReturnType<typeof useAuth>);
  const onLibraryChanged = vi.fn();
  const hook = renderHook(() => useLibraryRefresh(onLibraryChanged));
  return { fake, hook, onLibraryChanged };
}

const syncedAt = (fake: ReturnType<typeof fakeAccountsDb>, platform: string) =>
  fake.rows.find((r) => r.platform === platform)?.last_synced_at ?? null;

const assign = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  search.params = new URLSearchParams();
  vi.stubGlobal("location", { ...window.location, assign });
  vi.mocked(runLibrarySync).mockResolvedValue(steamJob("succeeded"));
  vi.mocked(completeXboxImport).mockResolvedValue({ status: "imported", summary: SUMMARY });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AC1 the refresh reads Refreshing while the sync runs", () => {
  it("is refreshing until the Steam sync finishes, with its progress", async () => {
    const steam = heldSteamSync();
    const { hook } = setup([STEAM]);
    await waitFor(() => expect(hook.result.current.canRefresh).toBe(true));

    act(() => hook.result.current.refresh());
    expect(hook.result.current.refreshing).toBe(true);
    await steam.report(steamJob("importing", { processed: 4, total: 10 }));
    expect(hook.result.current.statuses.steam).toEqual({
      state: "running", label: "Importing 4 of 10 Steam games…",
    });

    await steam.finish(steamJob("succeeded"));
    expect(hook.result.current.refreshing).toBe(false);
  });

  it("stays refreshing while the page leaves for the Xbox sign-in", async () => {
    const { hook } = setup([XBOX]);
    await waitFor(() => expect(hook.result.current.canRefresh).toBe(true));

    act(() => hook.result.current.refresh());

    expect(hook.result.current.refreshing).toBe(true);
    expect(assign).toHaveBeenCalledWith(XBOX_REFRESH_URL);
  });

  it("can't refresh with nothing syncable linked", async () => {
    const { hook } = setup([EPIC]);
    await waitFor(() => expect(hook.result.current.plan.epic).toBe(true));

    expect(hook.result.current.canRefresh).toBe(false);
  });
});

describe("AC2 every linked platform is re-synced and lastSyncedAt updated", () => {
  it("re-syncs Steam in place and stamps its sync time", async () => {
    const { fake, hook } = setup([STEAM]);
    await waitFor(() => expect(hook.result.current.canRefresh).toBe(true));

    await act(async () => hook.result.current.refresh());

    expect(runLibrarySync).toHaveBeenCalledWith(STEAM_ID, expect.any(Function), expect.anything());
    await waitFor(() => expect(syncedAt(fake, "STEAM")).not.toBeNull());
    expect(hook.result.current.statuses.steam).toEqual({
      state: "succeeded", message: "Steam: imported 10 games.",
    });
    expect(assign).not.toHaveBeenCalled();
    // The accounts are read again, so the new time shows without a reload.
    await waitFor(() =>
      expect(hook.result.current.lastSynced).toEqual(["Steam · Synced just now"]),
    );
  });

  it("signs in to Xbox first, remembering both platforms, before syncing anything", async () => {
    const { hook } = setup([STEAM, XBOX]);
    await waitFor(() => expect(hook.result.current.canRefresh).toBe(true));

    act(() => hook.result.current.refresh());

    expect(assign).toHaveBeenCalledWith(XBOX_REFRESH_URL);
    expect(runLibrarySync).not.toHaveBeenCalled();
    expect(takePending()).toEqual(["steam", "xbox"]);
  });

  it("back from the sign-in, imports Xbox and syncs Steam, stamping both", async () => {
    savePending(["steam", "xbox"]);
    search.params = new URLSearchParams("xbox=import-ready");

    const { fake, hook } = setup([STEAM, XBOX]);

    await waitFor(() => expect(syncedAt(fake, "XBOX")).not.toBeNull());
    await waitFor(() => expect(syncedAt(fake, "STEAM")).not.toBeNull());
    expect(completeXboxImport).toHaveBeenCalledTimes(1);
    expect(runLibrarySync).toHaveBeenCalledTimes(1);
    expect(hook.result.current.statuses.xbox).toEqual({
      state: "succeeded", message: "Imported 2 games from Xbox.",
    });
    expect(replace).toHaveBeenCalledWith("/library");
  });

  it("notes that Epic has nothing to sync", async () => {
    const { hook } = setup([STEAM, EPIC]);
    await waitFor(() => expect(hook.result.current.canRefresh).toBe(true));

    expect(hook.result.current.plan.epic).toBe(true);
    expect(hook.result.current.epicNote).toBe(
      "Epic games are added by hand or by CSV, so there's nothing to sync.",
    );
  });
});

describe("AC3 the library re-renders when the refresh finishes", () => {
  it("tells the page once, after every platform is done", async () => {
    savePending(["steam", "xbox"]);
    search.params = new URLSearchParams("xbox=import-ready");
    const steam = heldSteamSync();

    const { onLibraryChanged } = setup([STEAM, XBOX]);
    await waitFor(() => expect(completeXboxImport).toHaveBeenCalled());
    expect(onLibraryChanged).not.toHaveBeenCalled();

    await steam.finish(steamJob("succeeded"));

    await waitFor(() => expect(onLibraryChanged).toHaveBeenCalledTimes(1));
  });
});

describe("AC4 a failure offers a retry and leaves the data intact", () => {
  it("keeps the Xbox import and retries only the failed Steam sync", async () => {
    savePending(["steam", "xbox"]);
    search.params = new URLSearchParams("xbox=import-ready");
    vi.mocked(runLibrarySync).mockResolvedValueOnce(
      steamJob("failed", { error: "This Steam profile is private." }),
    );

    const { fake, hook } = setup([STEAM, XBOX]);
    await waitFor(() => expect(hook.result.current.hasFailures).toBe(true));
    expect(hook.result.current.statuses.steam).toEqual({
      state: "failed", message: "This Steam profile is private.",
    });
    expect(syncedAt(fake, "STEAM")).toBeNull(); // nothing synced, so no new sync time

    await act(async () => hook.result.current.retry());

    expect(runLibrarySync).toHaveBeenCalledTimes(2);
    expect(completeXboxImport).toHaveBeenCalledTimes(1);
    expect(assign).not.toHaveBeenCalled();
    await waitFor(() => expect(hook.result.current.statuses.steam?.state).toBe("succeeded"));
  });

  it("explains a failed Xbox sign-in and still syncs Steam", async () => {
    savePending(["steam", "xbox"]);
    search.params = new URLSearchParams("xbox=error&reason=private");

    const { fake, hook } = setup([STEAM, XBOX]);

    await waitFor(() => expect(syncedAt(fake, "STEAM")).not.toBeNull());
    expect(completeXboxImport).not.toHaveBeenCalled();
    expect(hook.result.current.statuses.xbox?.state).toBe("failed");
    expect(syncedAt(fake, "XBOX")).toBeNull();
  });

  it("retries a failed Xbox import with a new sign-in for Xbox alone", async () => {
    savePending(["steam", "xbox"]);
    search.params = new URLSearchParams("xbox=import-ready");
    const failed: XboxImportResult = { status: "error", reason: "import" };
    vi.mocked(completeXboxImport).mockResolvedValueOnce(failed);

    const { hook } = setup([STEAM, XBOX]);
    await waitFor(() => expect(hook.result.current.hasFailures).toBe(true));

    act(() => hook.result.current.retry());

    expect(assign).toHaveBeenCalledWith(XBOX_REFRESH_URL);
    expect(takePending()).toEqual(["xbox"]);
  });

  it("after an Xbox-only retry, doesn't sync Steam again", async () => {
    savePending(["xbox"]);
    search.params = new URLSearchParams("xbox=import-ready");

    const { hook } = setup([STEAM, XBOX]);

    await waitFor(() => expect(hook.result.current.statuses.xbox?.state).toBe("succeeded"));
    expect(runLibrarySync).not.toHaveBeenCalled();
  });

  it("reports a Steam sync it lost track of", async () => {
    vi.mocked(runLibrarySync).mockRejectedValueOnce(new Error("network"));
    const { hook } = setup([STEAM]);
    await waitFor(() => expect(hook.result.current.canRefresh).toBe(true));

    await act(async () => hook.result.current.refresh());

    expect(hook.result.current.statuses.steam).toEqual({
      state: "failed",
      message: "We lost track of the Steam sync. Check your library, or try again.",
    });
  });
});

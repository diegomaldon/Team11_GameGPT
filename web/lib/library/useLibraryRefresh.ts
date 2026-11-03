"use client";

// Manual library refresh with progress state. REQ006 · TM11-60.
//
// Refresh re-syncs every linked platform that can be synced (lib/library/libraryRefresh.ts
// says how). Each platform reports its own state, so one failing doesn't hide the others:
// a failed Steam sync rolls back on the server and a failed Xbox import saves nothing, so
// the library is left as it was, and Retry re-runs only the platforms that failed. Each
// success stamps that platform's last_synced_at with the user's own session (the API runs
// as the dev user and can't reach their row; see docs/steam-library.md), then the page is
// told to read its library again.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { formatLastSynced, markSynced } from "@/lib/account/linkedAccounts";
import { accountsDb, useLinkedAccounts } from "@/lib/account/useLinkedAccounts";
import { runLibrarySync } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/session";
import { completeXboxImport } from "@/lib/auth/xboxClient";
import {
  describeXboxErrorReason,
  describeXboxImport,
  describeXboxResult,
} from "@/lib/auth/xboxMessages";
import { PLATFORMS } from "@/lib/mock/data";
import {
  EPIC_NOTE,
  planRefresh,
  platformsToSync,
  savePending,
  steamProgress,
  takePending,
  XBOX_REFRESH_URL,
  type RefreshPlan,
  type RefreshPlatform,
} from "./libraryRefresh";

export type PlatformStatus =
  | { state: "running"; label: string }
  | { state: "succeeded"; message: string }
  | { state: "failed"; message: string };

export type LibraryRefresh = {
  /** At least one linked platform can be re-synced. */
  canRefresh: boolean;
  refreshing: boolean;
  statuses: Partial<Record<RefreshPlatform, PlatformStatus>>;
  hasFailures: boolean;
  plan: RefreshPlan;
  /** Shown when Epic is linked, which has nothing to sync. */
  epicNote: string | null;
  /** "Steam · Synced 5 min ago" for each platform a refresh covers. */
  lastSynced: string[];
  refresh: () => void;
  retry: () => void;
};

export const STEAM_FAILED_MESSAGE = "The Steam sync failed. Your Steam games are unchanged.";
export const STEAM_LOST_MESSAGE =
  "We lost track of the Steam sync. Check your library, or try again.";

/** What the Xbox sign-in came back with: ?xbox=import-ready, or a cancel or error. */
type XboxReturn = { result: string; reason: string | null };

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function useLibraryRefresh(onLibraryChanged: () => void): LibraryRefresh {
  const { user, status: authStatus } = useAuth();
  const userId = user?.id ?? null;
  const { state: accountsState, reload } = useLinkedAccounts(userId);
  const accounts = accountsState.status === "ready" ? accountsState.accounts : [];
  const plan = planRefresh(accounts);

  const [statuses, setStatuses] = useState<LibraryRefresh["statuses"]>({});
  const [isLeaving, setIsLeaving] = useState(false);
  const router = useRouter();
  const params = useSearchParams();
  const xboxResult = params.get("xbox");
  const xboxReason = params.get("reason");
  const isReturnHandled = useRef(false);
  const live = useRef(true);
  const steamPolling = useRef<AbortController | null>(null);
  const changed = useRef(onLibraryChanged);
  changed.current = onLibraryChanged;

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      steamPolling.current?.abort();
    };
  }, []);

  const setStatus = useCallback((platform: RefreshPlatform, status: PlatformStatus) => {
    if (live.current) {
      setStatuses((prev) => ({ ...prev, [platform]: status }));
    }
  }, []);

  const stampSynced = useCallback(
    async (platform: RefreshPlatform) => {
      if (userId) {
        // The games are in either way; a missing timestamp is not worth an error.
        await markSynced(accountsDb, userId, platform).catch(() => {});
      }
    },
    [userId],
  );

  const syncSteam = useCallback(
    async (steamId: string) => {
      steamPolling.current?.abort();
      const polling = new AbortController();
      steamPolling.current = polling;
      setStatus("steam", { state: "running", label: steamProgress(null) });
      try {
        const job = await runLibrarySync(
          steamId,
          (j) => setStatus("steam", { state: "running", label: steamProgress(j) }),
          { signal: polling.signal },
        );
        if (job.state === "succeeded") {
          await stampSynced("steam");
          setStatus("steam", {
            state: "succeeded",
            message: `Steam: imported ${plural(job.synced ?? 0, "game")}.`,
          });
        } else {
          setStatus("steam", { state: "failed", message: job.error ?? STEAM_FAILED_MESSAGE });
        }
      } catch {
        if (!polling.signal.aborted) {
          setStatus("steam", { state: "failed", message: STEAM_LOST_MESSAGE });
        }
      }
    },
    [setStatus, stampSynced],
  );

  const importXbox = useCallback(
    async ({ result, reason }: XboxReturn) => {
      if (result !== "import-ready") {
        const message = describeXboxResult(result, reason)?.message;
        setStatus("xbox", { state: "failed", message: message ?? describeXboxErrorReason(reason) });
        return;
      }
      setStatus("xbox", { state: "running", label: "Importing your Xbox games…" });
      const outcome = await completeXboxImport();
      if (outcome.status === "imported") {
        await stampSynced("xbox");
        const { message } = describeXboxImport(outcome.summary);
        setStatus("xbox", { state: "succeeded", message });
      } else {
        setStatus("xbox", { state: "failed", message: describeXboxErrorReason(outcome.reason) });
      }
    },
    [setStatus, stampSynced],
  );

  /** Runs the in-page part of a refresh, then has the page read its library again. */
  const run = useCallback(
    async (platforms: RefreshPlatform[], xbox: XboxReturn | null) => {
      const syncs: Promise<void>[] = [];
      if (platforms.includes("steam") && plan.steamId) {
        syncs.push(syncSteam(plan.steamId));
      }
      if (xbox) {
        syncs.push(importXbox(xbox));
      }
      await Promise.all(syncs);
      if (live.current) {
        reload();
        changed.current();
      }
    },
    [plan.steamId, syncSteam, importXbox, reload],
  );

  const start = useCallback(
    (platforms: RefreshPlatform[]) => {
      if (platforms.includes("xbox")) {
        // Xbox has to sign in first. Nothing syncs until the page is back.
        savePending(platforms);
        setIsLeaving(true);
        window.location.assign(XBOX_REFRESH_URL);
        return;
      }
      void run(platforms, null);
    },
    [run],
  );

  // Back from the Xbox sign-in: import Xbox and sync whatever else was pending.
  useEffect(() => {
    if (
      !xboxResult ||
      isReturnHandled.current ||
      authStatus === "loading" ||
      accountsState.status !== "ready"
    ) {
      return;
    }
    isReturnHandled.current = true;
    const pending = takePending() ?? platformsToSync(plan);
    router.replace("/library"); // so a reload doesn't import again
    void run(pending, { result: xboxResult, reason: xboxReason });
  }, [xboxResult, xboxReason, authStatus, accountsState.status, plan, router, run]);

  const refresh = useCallback(() => {
    setStatuses({});
    start(platformsToSync(plan));
  }, [plan, start]);

  const retry = useCallback(() => {
    const failed = (Object.keys(statuses) as RefreshPlatform[]).filter(
      (p) => statuses[p]?.state === "failed",
    );
    start(failed);
  }, [statuses, start]);

  const covered = platformsToSync(plan);
  const lastSynced = accounts
    .filter((a) => covered.includes(a.platform as RefreshPlatform))
    .map((a) => `${PLATFORMS[a.platform].label} · ${formatLastSynced(a.lastSyncedAt)}`);
  const all = Object.values(statuses);

  return {
    canRefresh: covered.length > 0,
    refreshing: isLeaving || all.some((s) => s.state === "running"),
    statuses,
    hasFailures: all.some((s) => s.state === "failed"),
    plan,
    epicNote: plan.epic ? EPIC_NOTE : null,
    lastSynced,
    refresh,
    retry,
  };
}

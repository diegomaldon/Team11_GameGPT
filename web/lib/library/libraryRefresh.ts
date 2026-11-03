// Manual library refresh: which linked platforms re-sync, and how. REQ006 · TM11-60.
//
// Steam re-syncs in place through the background import (TM11-49). Xbox keeps no
// token (ADR 0001 addendum), so every Xbox import starts with a Microsoft sign-in
// that leaves the page and comes back to /library?xbox=import-ready. The platforms
// still to sync are written to sessionStorage first, so the refresh carries on
// after that round trip. Epic games are added by hand or CSV, so there is nothing
// to sync for them.

import type { LinkedAccount } from "@/lib/account/linkedAccounts";
import type { LibrarySyncJob } from "@/lib/api/types";

export type RefreshPlatform = "steam" | "xbox";

export type RefreshPlan = {
  /** steamID64 of the linked Steam account, or null when Steam isn't linked. */
  steamId: string | null;
  xbox: boolean;
  epic: boolean;
};

export const XBOX_REFRESH_URL = "/api/xbox/login?next=/library&intent=import";

export const EPIC_NOTE = "Epic games are added by hand or by CSV, so there's nothing to sync.";

const PENDING_KEY = "gamegpt.libraryRefresh";
const REFRESH_PLATFORMS: readonly RefreshPlatform[] = ["steam", "xbox"];

export function planRefresh(accounts: LinkedAccount[]): RefreshPlan {
  const linked = (platform: string) =>
    accounts.find((a) => a.platform === platform && a.connected);
  return {
    steamId: linked("steam")?.accountId ?? null,
    xbox: linked("xbox") !== undefined,
    epic: linked("epic") !== undefined,
  };
}

/** The linked platforms a refresh can re-sync, Steam first. */
export function platformsToSync(plan: RefreshPlan): RefreshPlatform[] {
  return REFRESH_PLATFORMS.filter((p) => (p === "steam" ? plan.steamId !== null : plan.xbox));
}

/** Remembers what to sync once the Xbox sign-in comes back. Storage may be blocked. */
export function savePending(platforms: RefreshPlatform[]): void {
  try {
    window.sessionStorage.setItem(PENDING_KEY, JSON.stringify(platforms));
  } catch {
    // Without it, the return trip syncs every linked platform instead.
  }
}

/** Reads and forgets what savePending stored. Null when there is nothing usable. */
export function takePending(): RefreshPlatform[] | null {
  try {
    const raw = window.sessionStorage.getItem(PENDING_KEY);
    window.sessionStorage.removeItem(PENDING_KEY);
    const parsed: unknown = raw === null ? null : JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return null;
    }
    return REFRESH_PLATFORMS.filter((p) => parsed.includes(p));
  } catch {
    return null;
  }
}

export function steamProgress(job: LibrarySyncJob | null): string {
  if (!job || job.state === "queued") {
    return "Starting the Steam sync…";
  }
  if (job.state === "fetching") {
    return "Fetching your Steam library…";
  }
  return `Importing ${job.processed ?? 0} of ${job.total ?? 0} Steam games…`;
}

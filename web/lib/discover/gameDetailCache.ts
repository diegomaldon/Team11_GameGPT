// Game details already fetched this session, so the detail panel opens instantly the
// second time (TM11-78). Discover also prefetches the details of every pick as soon as
// results arrive, so the first open is usually instant too.
//
// Each GET /api/games/{game_id} costs about 2 s from a dev machine today (a new database
// connection per query), so this hides most of the wait. It keeps the promise, not just
// the value, so two opens of the same game while it's still loading share one request.
//
// Staleness: catalogue fields barely change, but `owned_on` does when the library does.
// The library page clears the cache whenever it reads the library, and an entry expires
// after CACHE_TTL_MS anyway. A failed read is never kept, so Try again really retries.

import { getGame } from "@/lib/api/client";
import type { GameDetail } from "@/lib/api/types";

export const CACHE_TTL_MS = 10 * 60 * 1000;
/** Enough for a long session of searches; the oldest entry goes first. */
export const CACHE_MAX_GAMES = 100;

type Entry = { at: number; promise: Promise<GameDetail>; value?: GameDetail };

const entries = new Map<string, Entry>();

function fresh(gameId: string, now: number): Entry | undefined {
  const entry = entries.get(gameId);
  if (entry && now - entry.at > CACHE_TTL_MS) {
    entries.delete(gameId);
    return undefined;
  }
  return entry;
}

/** The game's details, from the cache when they're there and still fresh. */
export function loadGame(gameId: string, now = Date.now()): Promise<GameDetail> {
  const cached = fresh(gameId, now);
  if (cached) return cached.promise;

  const entry: Entry = { at: now, promise: getGame(gameId) };
  entry.promise.then(
    (value) => {
      entry.value = value;
    },
    () => {
      // Only drop this entry: a later load may already have replaced it.
      if (entries.get(gameId) === entry) entries.delete(gameId);
    },
  );
  entries.set(gameId, entry);
  while (entries.size > CACHE_MAX_GAMES) {
    entries.delete(entries.keys().next().value as string);
  }
  return entry.promise;
}

/** Details that have already arrived, so the panel can skip its skeleton. */
export function peekGame(gameId: string, now = Date.now()): GameDetail | undefined {
  return fresh(gameId, now)?.value;
}

/** Start loading these games in the background. Failures are left for the panel to show. */
export function prefetchGames(gameIds: readonly (string | null | undefined)[]): void {
  for (const id of new Set(gameIds)) {
    if (id) loadGame(id).catch(() => {});
  }
}

/** Forget everything, e.g. after the library changed and `owned_on` may be stale. */
export function clearGameCache(): void {
  entries.clear();
}

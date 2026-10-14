// Library sort, title search and the saved view (TM11-51).
//
// Search and sort run client-side, over the merged list from unified.ts. They
// can't run on the server: GET /api/library returns the whole library unpaged,
// and hand-added games live only in the browser's mock store, so a server-side
// search would miss them. Kept free of React so it can be tested directly.
//
// The view (sort, search, platform filter) is saved to sessionStorage so it
// survives navigating to another page and back within the tab.

import type { GamePlatform } from "../mock/data";
import { normalizeTitle, PLATFORM_ORDER, type UnifiedGame } from "./unified";

export type LibrarySort = "playtime-desc" | "playtime-asc" | "title-asc" | "title-desc";

export type PlatformFilter = "all" | GamePlatform;

export type LibraryView = {
  sort: LibrarySort;
  query: string;
  platform: PlatformFilter;
};

export const SORT_OPTIONS: { key: LibrarySort; label: string }[] = [
  { key: "playtime-desc", label: "Most played" },
  { key: "playtime-asc", label: "Least played" },
  { key: "title-asc", label: "Title A–Z" },
  { key: "title-desc", label: "Title Z–A" },
];

/** Most played first, matching the order GET /api/library returns. */
export const DEFAULT_VIEW: LibraryView = { sort: "playtime-desc", query: "", platform: "all" };

export const VIEW_STORAGE_KEY = "gamegpt.library.view.v1";

// Same settings as unified.ts: `numeric` puts "Game 2" before "Game 10".
const byTitle = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

/**
 * A sorted copy of `rows`. Ties on playtime fall back to A-Z, so hand-added
 * games (no playtime) and unplayed imports still come out in a stable order.
 */
export function sortRows(rows: UnifiedGame[], sort: LibrarySort): UnifiedGame[] {
  const out = [...rows];
  switch (sort) {
    case "playtime-desc":
      return out.sort(
        (a, b) => b.playtimeMinutes - a.playtimeMinutes || byTitle.compare(a.title, b.title),
      );
    case "playtime-asc":
      return out.sort(
        (a, b) => a.playtimeMinutes - b.playtimeMinutes || byTitle.compare(a.title, b.title),
      );
    case "title-asc":
      return out.sort((a, b) => byTitle.compare(a.title, b.title));
    case "title-desc":
      return out.sort((a, b) => byTitle.compare(b.title, a.title));
  }
}

/** normalizeTitle with the spaces removed, so word breaks don't matter. */
function searchKey(title: string): string {
  return normalizeTitle(title).replace(/ /g, "");
}

/**
 * Rows whose title contains `query`. Both sides go through normalizeTitle, so
 * "doom" finds "DOOM™" and "pokemon" finds "Pokémon". Spaces are dropped too:
 * normalizeTitle turns punctuation into a space, so without that "assassins
 * creed" would miss "Assassin's Creed" and "halflife" would miss "Half-Life 2".
 * A blank query keeps all.
 */
export function searchRows(rows: UnifiedGame[], query: string): UnifiedGame[] {
  const needle = searchKey(query);
  if (!needle) {
    return rows;
  }
  return rows.filter((r) => searchKey(r.title).includes(needle));
}

const SORTS = new Set<string>(SORT_OPTIONS.map((o) => o.key));
const PLATFORMS = new Set<string>(["all", ...PLATFORM_ORDER]);

/**
 * The saved view, or the default. Every field is checked on its own, so one
 * stale or hand-edited value can't break the page or wipe the others.
 */
export function loadView(): LibraryView {
  let raw: string | null = null;
  try {
    raw = window.sessionStorage.getItem(VIEW_STORAGE_KEY);
  } catch {
    // Storage blocked (private mode, sandboxed frame): start from the default.
    return DEFAULT_VIEW;
  }
  if (!raw) {
    return DEFAULT_VIEW;
  }
  let saved: Partial<Record<keyof LibraryView, unknown>>;
  try {
    saved = JSON.parse(raw) ?? {};
  } catch {
    return DEFAULT_VIEW;
  }
  return {
    sort:
      typeof saved.sort === "string" && SORTS.has(saved.sort)
        ? (saved.sort as LibrarySort)
        : DEFAULT_VIEW.sort,
    query: typeof saved.query === "string" ? saved.query : DEFAULT_VIEW.query,
    platform:
      typeof saved.platform === "string" && PLATFORMS.has(saved.platform)
        ? (saved.platform as PlatformFilter)
        : DEFAULT_VIEW.platform,
  };
}

export function saveView(view: LibraryView): void {
  try {
    window.sessionStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(view));
  } catch {
    // Not saving only costs the user their view on return; the page still works.
  }
}

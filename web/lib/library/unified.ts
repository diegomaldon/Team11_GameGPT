// One list of everything a user owns, across platforms (TM11-50).
//
// Two sources feed the library view:
//   - GET /api/library: what a platform import wrote to owned_games (Steam today)
//   - the mock store: games the user added by hand, on any platform
//
// The same game owned twice (Forza on Steam and on Xbox) is one row with two
// badges, not two rows. Kept free of React so the merge can be tested directly
// and run on thousands of titles without a render in the way.

import type { LibraryItem } from "../api/types";
import type { GamePlatform, OwnedGame } from "../mock/data";

export type UnifiedGame = {
  key: string;
  title: string;
  appid?: number;
  /** Platforms this title is owned on, in PLATFORM_ORDER. */
  platforms: GamePlatform[];
  /** Lifetime minutes from an import. Manual entries carry none. */
  playtimeMinutes: number;
  /** True when at least one copy came from a platform import. */
  imported: boolean;
  /** Mock-store ids of hand-added copies; the only part a user can remove. */
  manualIds: string[];
};

/** Badge order, so a row's badges never reshuffle between renders. */
export const PLATFORM_ORDER: GamePlatform[] = ["steam", "xbox", "epic", "playstation", "other"];

const KNOWN = new Set<string>(PLATFORM_ORDER);

function toPlatform(value: string | null | undefined): GamePlatform {
  const p = (value ?? "").toLowerCase();
  return KNOWN.has(p) ? (p as GamePlatform) : "other";
}

/**
 * Title key for matching copies across platforms. Case, trademark marks and
 * punctuation differ between stores ("DOOM™" vs "Doom"), so they are ignored.
 */
export function normalizeTitle(title: string): string {
  return title
    // Strip marks first: NFKD would otherwise turn "™" into the letters "TM".
    .replace(/[™®©]/g, "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

type Entry = {
  title: string;
  platform: GamePlatform;
  appid?: number;
  playtimeMinutes: number;
  imported: boolean;
  manualId?: string;
};

/**
 * Merge imported and hand-added games into one row per title.
 *
 * Copies join on Steam appid first, then on normalized title. Two copies that
 * both carry a Steam appid and disagree are different games that happen to
 * share a name, so they stay separate rows.
 *
 * Sorted by playtime, most played first, then A-Z. That matches the order
 * GET /api/library already returns, and puts what the user plays at the top.
 */
export function mergeLibrary(imported: LibraryItem[], manual: OwnedGame[]): UnifiedGame[] {
  const entries: Entry[] = [
    ...imported.map((i) => ({
      title: i.title,
      platform: toPlatform(i.platform),
      appid: i.steam_appid ?? undefined,
      playtimeMinutes: Math.max(0, i.playtime_minutes ?? 0),
      imported: true,
    })),
    ...manual.map((g) => ({
      title: g.title,
      platform: g.platform,
      appid: g.appid,
      playtimeMinutes: 0,
      imported: false,
      manualId: g.id,
    })),
  ];

  const rows = new Map<string, UnifiedGame>();
  const keyByAppid = new Map<number, string>();
  const keyByTitle = new Map<string, string>();

  for (const e of entries) {
    const norm = normalizeTitle(e.title);
    let key = e.appid !== undefined ? keyByAppid.get(e.appid) : undefined;

    if (key === undefined && norm) {
      const titled = keyByTitle.get(norm);
      const existing = titled !== undefined ? rows.get(titled) : undefined;
      const conflict =
        existing?.appid !== undefined && e.appid !== undefined && existing.appid !== e.appid;
      if (existing && !conflict) key = titled;
    }

    let row = key !== undefined ? rows.get(key) : undefined;
    if (!row) {
      key = `row-${rows.size}`;
      row = {
        key,
        title: e.title || (e.appid !== undefined ? `App ${e.appid}` : "Untitled"),
        appid: e.appid,
        platforms: [],
        playtimeMinutes: 0,
        imported: false,
        manualIds: [],
      };
      rows.set(key, row);
    }

    if (!row.platforms.includes(e.platform)) row.platforms.push(e.platform);
    row.playtimeMinutes = Math.max(row.playtimeMinutes, e.playtimeMinutes);
    row.imported ||= e.imported;
    if (e.manualId) row.manualIds.push(e.manualId);
    if (row.appid === undefined && e.appid !== undefined) row.appid = e.appid;

    if (row.appid !== undefined) keyByAppid.set(row.appid, row.key);
    if (norm && !keyByTitle.has(norm)) keyByTitle.set(norm, row.key);
  }

  const out = [...rows.values()];
  for (const row of out) {
    row.platforms.sort((a, b) => PLATFORM_ORDER.indexOf(a) - PLATFORM_ORDER.indexOf(b));
  }
  return out.sort(
    (a, b) => b.playtimeMinutes - a.playtimeMinutes || a.title.localeCompare(b.title),
  );
}

/** Rows per platform for the filter chips, in one pass rather than one per chip. */
export function countByPlatform(rows: UnifiedGame[]): Record<GamePlatform, number> {
  const counts = { steam: 0, xbox: 0, epic: 0, playstation: 0, other: 0 };
  for (const row of rows) for (const p of row.platforms) counts[p] += 1;
  return counts;
}

/** "2,155 h", "45 min", or null when there is nothing worth showing. */
export function formatPlaytime(minutes: number): string | null {
  if (minutes <= 0) return null;
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60).toLocaleString("en-US")} h`;
}

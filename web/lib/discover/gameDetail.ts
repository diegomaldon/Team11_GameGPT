// What the game detail panel shows, and how (TM11-78, REQ009). Kept free of React so
// the rules can be tested directly.
//
// The panel opens from three places: a recommendation card, a library game and a
// past search. Each knows a little about the game (its id, title and art), so it
// opens the panel with a DetailTarget; the panel fetches the rest from
// GET /api/games/{game_id}. A missing field reads UNAVAILABLE, never a blank or a
// broken value.

import type {
  GameDetail,
  HistoryRecommendation,
  LibraryItem,
  Recommendation,
} from "@/lib/api/types";
import type { UnifiedGame } from "@/lib/library/unified";
import { platformLabels, scorePct } from "@/lib/discover/recommendations";

export const UNAVAILABLE = "Unavailable";

/** At most this many tags, after the genres. Hosted games carry up to 25. */
export const MAX_TAGS = 8;

/** What a surface knows about a game when it opens the panel. */
export type DetailTarget = {
  /** null when the game isn't in the catalogue: nothing more can be fetched. */
  gameId: string | null;
  title: string;
  steamAppid?: number | null;
  /** Why it was recommended, from a card or a past search. */
  reason?: string | null;
  /** Shown before the fetch lands. */
  platforms?: readonly string[] | null;
};

export function targetFromRecommendation(rec: Recommendation): DetailTarget {
  return {
    gameId: rec.game_id ?? null,
    title: rec.title,
    steamAppid: rec.steam_appid,
    reason: rec.reason,
    platforms: rec.platforms,
  };
}

export function targetFromHistory(rec: HistoryRecommendation): DetailTarget {
  return {
    gameId: rec.game_id ?? null,
    title: rec.title,
    steamAppid: rec.steam_appid,
    reason: rec.reason,
  };
}

export function targetFromLibrary(
  row: Pick<UnifiedGame, "gameId" | "title" | "appid">,
): DetailTarget {
  return {
    gameId: row.gameId ?? null,
    title: row.title,
    steamAppid: row.appid,
  };
}

export function targetFromLibraryItem(item: LibraryItem): DetailTarget {
  return {
    gameId: item.game_id ?? null,
    title: item.title,
    steamAppid: item.steam_appid,
  };
}

/** "85% positive", or UNAVAILABLE. Players' scores are a share of positive reviews. */
export function userScoreText(score?: number | null): string {
  const pct = scorePct(score);
  return pct == null ? UNAVAILABLE : `${pct}% positive`;
}

/** "69 / 100", or UNAVAILABLE. Critics' scores read as a Metacritic-style mark. */
export function criticScoreText(score?: number | null): string {
  const pct = scorePct(score);
  return pct == null ? UNAVAILABLE : `${pct} / 100`;
}

/** "Steam, Xbox", or UNAVAILABLE. */
export function platformsText(platforms?: readonly string[] | null): string {
  const labels = platformLabels(platforms);
  return labels.length > 0 ? labels.join(", ") : UNAVAILABLE;
}

/** "2018", or UNAVAILABLE. The API sends an ISO date. */
export function releaseYearText(date?: string | null): string {
  const year = date ? Number.parseInt(date.slice(0, 4), 10) : Number.NaN;
  return Number.isFinite(year) && year > 0 ? String(year) : UNAVAILABLE;
}

/** "Facepunch Studios", "A, B", or UNAVAILABLE. */
export function namesText(names?: readonly string[] | null): string {
  const clean = (names ?? []).map((n) => n.trim()).filter(Boolean);
  return clean.length > 0 ? clean.join(", ") : UNAVAILABLE;
}

/**
 * Genres, then up to MAX_TAGS tags, each once whatever its case. Tags that repeat a
 * genre ("Survival" and "survival") would read as noise.
 */
export function genreTags(detail: Pick<GameDetail, "genres" | "tags">): {
  genres: string[];
  tags: string[];
} {
  const seen = new Set<string>();
  const once = (values: readonly string[] | undefined, limit = Infinity) => {
    const out: string[] = [];
    for (const raw of values ?? []) {
      const value = raw.trim();
      const key = value.toLowerCase();
      if (!value || seen.has(key)) continue;
      seen.add(key);
      out.push(value);
      if (out.length >= limit) break;
    }
    return out;
  };
  const genres = once(detail.genres);
  return { genres, tags: once(detail.tags, MAX_TAGS) };
}

/** Store links to show, in the library's badge order. Only links the API sent. */
export function storeLinks(
  links?: Record<string, string> | null,
): { label: string; href: string }[] {
  const entries = Object.entries(links ?? {}).filter(([, href]) => /^https?:\/\//.test(href));
  const labels = platformLabels(entries.map(([platform]) => platform));
  const byLabel = new Map(
    entries.map(([platform, href]) => [platformLabels([platform])[0], href] as const),
  );
  return labels.map((label) => ({ label, href: byLabel.get(label)! }));
}

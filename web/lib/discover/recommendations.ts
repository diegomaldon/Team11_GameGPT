// Shaping recommend results for the Discover cards (TM11-75, REQ015). Kept free of
// React so the rules can be tested directly.

import type { Recommendation } from "@/lib/api/types";
import { GAME_PLATFORM_LABEL, type GamePlatform } from "@/lib/mock/data";
import { PLATFORM_ORDER } from "@/lib/library/unified";

/** REQ015: the pipeline returns 3 to 5 picks; never show more than 5. */
export const MAX_CARDS = 5;

/**
 * The picks in the pipeline's rank order, at most MAX_CARDS. Sorted by `rank`
 * rather than trusting array order, so rank 1 is always first; ties keep the
 * order the API sent them in.
 */
export function rankedCards(recs: readonly Recommendation[]): Recommendation[] {
  return recs
    .map((rec, i) => ({ rec, i }))
    .sort((a, b) => a.rec.rank - b.rec.rank || a.i - b.i)
    .slice(0, MAX_CARDS)
    .map(({ rec }) => rec);
}

/** A 0–1 or 0–100 review score as a whole percentage, or null when there is none. */
export function scorePct(score?: number | null): number | null {
  if (score == null || Number.isNaN(score)) return null;
  return Math.round(score <= 1 ? score * 100 : score);
}

/**
 * Store labels for a pick's platforms, in the library's badge order, each once.
 * Unknown stores are kept, title-cased, after the known ones.
 */
export function platformLabels(platforms?: readonly string[] | null): string[] {
  const seen = new Set<string>();
  const known: GamePlatform[] = [];
  const other: string[] = [];
  for (const raw of platforms ?? []) {
    const p = raw.trim().toLowerCase();
    if (!p || seen.has(p)) continue;
    seen.add(p);
    if ((PLATFORM_ORDER as string[]).includes(p) && p !== "other") known.push(p as GamePlatform);
    else other.push(p.charAt(0).toUpperCase() + p.slice(1));
  }
  known.sort((a, b) => PLATFORM_ORDER.indexOf(a) - PLATFORM_ORDER.indexOf(b));
  return [...known.map((p) => GAME_PLATFORM_LABEL[p]), ...other];
}

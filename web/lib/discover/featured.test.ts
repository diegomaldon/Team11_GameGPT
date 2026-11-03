// TM11-142. The Discover page's curated games and prompts.
import { describe, expect, it } from "vitest";
import {
  POPULAR,
  PROMPT_GROUPS,
  SPOTLIGHT,
  promptLike,
  steamCoverUrl,
  steamHeroUrl,
} from "./featured";

describe("featured games", () => {
  it("has three spotlight games, each with a blurb", () => {
    expect(SPOTLIGHT).toHaveLength(3);
    for (const g of SPOTLIGHT) {
      expect(g.blurb.trim().length).toBeGreaterThan(20);
    }
  });

  it("lists each popular game once", () => {
    const ids = POPULAR.map((g) => g.steamAppId);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("builds Steam art URLs from the app id", () => {
    expect(steamCoverUrl(620)).toBe(
      "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/620/library_600x900.jpg",
    );
    expect(steamHeroUrl(1145360)).toMatch(/\/1145360\/library_hero\.jpg$/);
  });
});

describe("suggested prompts", () => {
  it("covers mood, genre, comparison and platform", () => {
    expect(PROMPT_GROUPS.map((g) => g.label)).toEqual([
      "Mood",
      "Genre",
      "Like a game you love",
      "Where you play",
    ]);
  });

  it("fits within the recommend query limit", () => {
    const all = [...PROMPT_GROUPS.flatMap((g) => g.prompts), ...POPULAR.map((g) => promptLike(g.title))];
    for (const p of all) {
      expect(p.length).toBeLessThanOrEqual(500);
    }
  });
});

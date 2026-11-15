// TM11-142. The Discover page's curated games and prompts.
import { describe, expect, it } from "vitest";
import {
  EXAMPLE_PROMPTS,
  POPULAR,
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

describe("example prompts (TM11-74)", () => {
  it("has exactly three, one each for mood, comparison and platform", () => {
    expect(EXAMPLE_PROMPTS.map((e) => e.label)).toEqual([
      "Mood",
      "Like a game you love",
      "Where you play",
    ]);
  });

  it("has no duplicate prompts", () => {
    const prompts = EXAMPLE_PROMPTS.map((e) => e.prompt);
    expect(new Set(prompts).size).toBe(prompts.length);
  });

  it("fits within the recommend query limit", () => {
    const all = [...EXAMPLE_PROMPTS.map((e) => e.prompt), ...POPULAR.map((g) => promptLike(g.title))];
    for (const p of all) {
      expect(p.length).toBeLessThanOrEqual(500);
    }
  });
});

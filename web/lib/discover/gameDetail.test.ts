// TM11-78. How the detail panel words each field, and what each surface opens it with.
import { describe, expect, it } from "vitest";
import {
  criticScoreText,
  genreTags,
  MAX_TAGS,
  namesText,
  platformsText,
  releaseYearText,
  storeLinks,
  targetFromHistory,
  targetFromLibrary,
  targetFromRecommendation,
  UNAVAILABLE,
  userScoreText,
} from "./gameDetail";
import { mergeLibrary } from "@/lib/library/unified";

describe("field text: a missing value reads Unavailable", () => {
  it("scores", () => {
    expect(userScoreText(0.85)).toBe("85% positive");
    expect(criticScoreText(0.69)).toBe("69 / 100");
    expect(criticScoreText(0)).toBe("0 / 100"); // zero is a score, not a missing one
    for (const missing of [null, undefined, Number.NaN]) {
      expect(userScoreText(missing)).toBe(UNAVAILABLE);
      expect(criticScoreText(missing)).toBe(UNAVAILABLE);
    }
  });

  it("platforms, in badge order", () => {
    expect(platformsText(["xbox", "steam"])).toBe("Steam, Xbox");
    expect(platformsText([])).toBe(UNAVAILABLE);
    expect(platformsText(null)).toBe(UNAVAILABLE);
  });

  it("release year", () => {
    expect(releaseYearText("2018-02-08")).toBe("2018");
    expect(releaseYearText(null)).toBe(UNAVAILABLE);
    expect(releaseYearText("soon")).toBe(UNAVAILABLE);
  });

  it("developer names", () => {
    expect(namesText(["Mega Crit", "Humble"])).toBe("Mega Crit, Humble");
    expect(namesText(["", "  "])).toBe(UNAVAILABLE);
  });
});

describe("genre tags", () => {
  it("lists genres, then tags, each once whatever its case", () => {
    expect(genreTags({ genres: ["Survival", " Multiplayer "], tags: ["survival", "PvP", ""] })).toEqual({
      genres: ["Survival", "Multiplayer"],
      tags: ["PvP"],
    });
  });

  it(`keeps at most ${MAX_TAGS} tags`, () => {
    const tags = Array.from({ length: 25 }, (_, i) => `Tag ${i}`);
    expect(genreTags({ genres: [], tags }).tags).toHaveLength(MAX_TAGS);
  });
});

describe("store links", () => {
  it("only uses http(s) links the API sent, in badge order", () => {
    expect(
      storeLinks({
        xbox: "https://www.xbox.com/games/store/x",
        steam: "https://store.steampowered.com/app/1",
        epic: "javascript:alert(1)",
      }),
    ).toEqual([
      { label: "Steam", href: "https://store.steampowered.com/app/1" },
      { label: "Xbox", href: "https://www.xbox.com/games/store/x" },
    ]);
    expect(storeLinks({})).toEqual([]);
    expect(storeLinks(null)).toEqual([]);
  });
});

describe("AC2: what each surface opens the panel with", () => {
  it("a recommendation card", () => {
    expect(
      targetFromRecommendation({
        rank: 1,
        game_id: "g1",
        title: "Hades",
        reason: "Fast runs.",
        steam_appid: 1145360,
        platforms: ["steam"],
      }),
    ).toEqual({
      gameId: "g1",
      title: "Hades",
      steamAppid: 1145360,
      reason: "Fast runs.",
      platforms: ["steam"],
    });
  });

  it("a past search's result", () => {
    expect(targetFromHistory({ rank: 2, game_id: null, title: "Gone", reason: null })).toEqual({
      gameId: null,
      title: "Gone",
      steamAppid: undefined,
      reason: null,
    });
  });

  it("a library game, whose catalogue id survives the merge across platforms", () => {
    const [row] = mergeLibrary(
      [{ game_id: "g-rust", title: "Rust", steam_appid: 252490, platform: "steam", playtime_minutes: 5 }],
      [{ id: "m1", title: "Rust", platform: "xbox", appid: 252490 }],
    );
    expect(row.platforms).toEqual(["steam", "xbox"]);
    expect(targetFromLibrary(row)).toEqual({ gameId: "g-rust", title: "Rust", steamAppid: 252490 });
  });

  it("a hand-added game with no catalogue id", () => {
    const [row] = mergeLibrary([], [{ id: "m1", title: "Indie Thing", platform: "epic" }]);
    expect(targetFromLibrary(row).gameId).toBeNull();
  });
});

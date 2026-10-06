import { describe, expect, it } from "vitest";
import type { LibraryItem } from "../api/types";
import type { OwnedGame } from "../mock/data";
import {
  countByPlatform,
  formatPlaytime,
  mergeLibrary,
  normalizeTitle,
} from "./unified";

function steam(title: string, appid: number, playtime = 0): LibraryItem {
  return { title, steam_appid: appid, platform: "steam", playtime_minutes: playtime };
}

function manual(id: string, title: string, platform: OwnedGame["platform"], appid?: number) {
  return { id, title, platform, appid } satisfies OwnedGame;
}

describe("mergeLibrary (TM11-50 AC: owned titles listed with per-platform badges)", () => {
  it("lists imported and hand-added games together", () => {
    const rows = mergeLibrary(
      [steam("Rust", 252490, 129351)],
      [manual("g1", "Halo Infinite", "xbox")],
    );
    expect(rows.map((r) => [r.title, r.platforms])).toEqual([
      ["Rust", ["steam"]],
      ["Halo Infinite", ["xbox"]],
    ]);
  });

  it("shows a game owned on two platforms once, with a badge for each", () => {
    const rows = mergeLibrary(
      [steam("Forza Horizon 5", 1551360, 4577)],
      [manual("g4", "Forza Horizon 5", "xbox")],
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      title: "Forza Horizon 5",
      platforms: ["steam", "xbox"],
      appid: 1551360,
      playtimeMinutes: 4577,
      imported: true,
      manualIds: ["g4"],
    });
  });

  it("matches titles across stores despite case and trademark marks", () => {
    const rows = mergeLibrary([steam("DOOM™", 379720)], [manual("g1", "Doom", "epic")]);
    expect(rows).toHaveLength(1);
    expect(rows[0].platforms).toEqual(["steam", "epic"]);
  });

  it("joins on Steam appid even when the titles are spelled differently", () => {
    const rows = mergeLibrary(
      [steam("The Witcher 3: Wild Hunt — Remastered", 292030, 13136)],
      [manual("g1", "The Witcher 3", "steam", 292030)],
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].manualIds).toEqual(["g1"]);
  });

  it("keeps two different Steam apps apart even when they share a name", () => {
    const rows = mergeLibrary([steam("HITMAN", 236870), steam("HITMAN", 863550)], []);
    expect(rows).toHaveLength(2);
  });

  it("does not repeat a badge when one platform lists a game twice", () => {
    const rows = mergeLibrary([steam("Rust", 252490)], [manual("g1", "Rust", "steam")]);
    expect(rows[0].platforms).toEqual(["steam"]);
  });

  it("orders badges the same way on every row", () => {
    const rows = mergeLibrary(
      [steam("Celeste", 504230)],
      [manual("a", "Celeste", "playstation"), manual("b", "Celeste", "xbox")],
    );
    expect(rows[0].platforms).toEqual(["steam", "xbox", "playstation"]);
  });

  it("shows a platform the UI does not know yet as Other, not as nothing", () => {
    const rows = mergeLibrary([{ title: "Some Game", platform: "gog", playtime_minutes: 0 }], []);
    expect(rows[0].platforms).toEqual(["other"]);
  });

  it("puts the most played first, then A to Z", () => {
    const rows = mergeLibrary(
      [steam("Balatro", 2379780, 671), steam("Rust", 252490, 129351), steam("Abzu", 384190, 0)],
      [manual("g1", "Celeste", "steam")],
    );
    expect(rows.map((r) => r.title)).toEqual(["Rust", "Balatro", "Abzu", "Celeste"]);
  });

  it("names an untitled import by its appid instead of a blank row", () => {
    expect(mergeLibrary([steam("", 440)], [])[0].title).toBe("App 440");
  });

  it("keeps each row's key when other games are added or removed", () => {
    // Keys are React identity. If they shift, removing one game hands its DOM
    // node (and keyboard focus on its Remove button) to the next game.
    const imported = [steam("Rust", 252490)];
    const before = mergeLibrary(imported, [
      manual("a", "Halo Infinite", "xbox"),
      manual("b", "Celeste", "playstation"),
    ]);
    const removed = mergeLibrary(imported, [manual("b", "Celeste", "playstation")]);
    const added = mergeLibrary(imported, [
      manual("c", "Hades", "epic"), // addGame prepends
      manual("a", "Halo Infinite", "xbox"),
      manual("b", "Celeste", "playstation"),
    ]);
    const keyOf = (rows: typeof before, title: string) => rows.find((r) => r.title === title)?.key;
    for (const rows of [removed, added]) {
      expect(keyOf(rows, "Celeste")).toBe(keyOf(before, "Celeste"));
      expect(keyOf(rows, "Rust")).toBe(keyOf(before, "Rust"));
      expect(new Set(rows.map((r) => r.key)).size).toBe(rows.length);
    }
  });

  it("sorts numbered titles in number order", () => {
    const rows = mergeLibrary([], [manual("a", "Game 10", "steam"), manual("b", "Game 2", "steam")]);
    expect(rows.map((r) => r.title)).toEqual(["Game 2", "Game 10"]);
  });

  it("handles 5,000 titles", () => {
    const items = Array.from({ length: 5000 }, (_, i) => steam(`Game ${i}`, 1000 + i, i));
    const rows = mergeLibrary(items, [manual("g1", "Game 42", "xbox")]);
    expect(rows).toHaveLength(5000);
    expect(rows[0].title).toBe("Game 4999");
    expect(rows.find((r) => r.title === "Game 42")?.platforms).toEqual(["steam", "xbox"]);
  });
});

describe("countByPlatform", () => {
  it("counts a two-platform game under both platforms", () => {
    const rows = mergeLibrary(
      [steam("Forza Horizon 5", 1551360), steam("Rust", 252490)],
      [manual("g4", "Forza Horizon 5", "xbox")],
    );
    expect(countByPlatform(rows)).toEqual({ steam: 2, xbox: 1, epic: 0, playstation: 0, other: 0 });
  });
});

describe("normalizeTitle", () => {
  it("drops case, marks, accents and punctuation", () => {
    expect(normalizeTitle("Pokémon™: Let's Go!")).toBe("pokemon let s go");
  });
});

describe("formatPlaytime", () => {
  it("formats minutes and hours, and hides zero", () => {
    expect(formatPlaytime(0)).toBeNull();
    expect(formatPlaytime(45)).toBe("45 min");
    expect(formatPlaytime(129351)).toBe("2,155 h");
  });
});

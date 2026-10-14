// @vitest-environment jsdom

// TM11-51: sort, title search and the saved library view.

import { afterEach, describe, expect, it, vi } from "vitest";
import type { UnifiedGame } from "./unified";
import {
  DEFAULT_VIEW,
  loadView,
  saveView,
  searchRows,
  sortRows,
  VIEW_STORAGE_KEY,
} from "./view";

function game(title: string, playtimeMinutes = 0): UnifiedGame {
  return {
    key: `title-${title}`,
    title,
    platforms: ["steam"],
    playtimeMinutes,
    imported: true,
    manualIds: [],
  };
}

const titles = (rows: UnifiedGame[]) => rows.map((r) => r.title);

const LIBRARY = [game("Rust", 500), game("Celeste", 0), game("Hades", 120), game("Balatro", 0)];

describe("sortRows: AC1 sortable by title and playtime", () => {
  it("puts the most played first, breaking ties A-Z", () => {
    expect(titles(sortRows(LIBRARY, "playtime-desc"))).toEqual([
      "Rust",
      "Hades",
      "Balatro",
      "Celeste",
    ]);
  });

  it("puts the least played first, breaking ties A-Z", () => {
    expect(titles(sortRows(LIBRARY, "playtime-asc"))).toEqual([
      "Balatro",
      "Celeste",
      "Hades",
      "Rust",
    ]);
  });

  it("sorts by title both ways", () => {
    expect(titles(sortRows(LIBRARY, "title-asc"))).toEqual(["Balatro", "Celeste", "Hades", "Rust"]);
    expect(titles(sortRows(LIBRARY, "title-desc"))).toEqual([
      "Rust",
      "Hades",
      "Celeste",
      "Balatro",
    ]);
  });

  it("orders numbered titles numerically and ignores case", () => {
    const rows = [game("Game 10"), game("game 2"), game("Game 1")];
    expect(titles(sortRows(rows, "title-asc"))).toEqual(["Game 1", "game 2", "Game 10"]);
  });

  it("does not reorder the list it was given", () => {
    const rows = [...LIBRARY];
    sortRows(rows, "title-asc");
    expect(rows).toEqual(LIBRARY);
  });
});

describe("searchRows: AC2 title search, client-side", () => {
  it("matches part of a title, ignoring case", () => {
    expect(titles(searchRows(LIBRARY, "ADE"))).toEqual(["Hades"]);
  });

  it("ignores trademark marks, accents and punctuation", () => {
    const rows = [game("DOOM™"), game("Pokémon Legends"), game("Half-Life 2")];
    expect(titles(searchRows(rows, "doom"))).toEqual(["DOOM™"]);
    expect(titles(searchRows(rows, "pokemon"))).toEqual(["Pokémon Legends"]);
    expect(titles(searchRows(rows, "half life"))).toEqual(["Half-Life 2"]);
  });

  it("keeps everything for a blank or punctuation-only query", () => {
    expect(searchRows(LIBRARY, "")).toBe(LIBRARY);
    expect(searchRows(LIBRARY, "   ")).toBe(LIBRARY);
    expect(searchRows(LIBRARY, "--")).toBe(LIBRARY);
  });

  it("returns nothing when no title matches", () => {
    expect(searchRows(LIBRARY, "zelda")).toEqual([]);
  });
});

describe("loadView / saveView: AC4 view survives navigating away and back", () => {
  afterEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("round-trips the sort, search and platform filter", () => {
    saveView({ sort: "title-desc", query: "hades", platform: "xbox" });
    expect(loadView()).toEqual({ sort: "title-desc", query: "hades", platform: "xbox" });
  });

  it("starts from the default when nothing is saved", () => {
    expect(loadView()).toEqual(DEFAULT_VIEW);
  });

  it("falls back to the default for unreadable JSON", () => {
    window.sessionStorage.setItem(VIEW_STORAGE_KEY, "{not json");
    expect(loadView()).toEqual(DEFAULT_VIEW);
  });

  it("drops a bad field without losing the good ones", () => {
    window.sessionStorage.setItem(
      VIEW_STORAGE_KEY,
      JSON.stringify({ sort: "by-vibes", query: "rust", platform: 42 }),
    );
    expect(loadView()).toEqual({ ...DEFAULT_VIEW, query: "rust" });
  });

  it("works when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(() => saveView({ ...DEFAULT_VIEW, query: "x" })).not.toThrow();
    expect(loadView()).toEqual(DEFAULT_VIEW);
  });
});

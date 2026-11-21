// @vitest-environment jsdom

// TM11-76: the placeholders shown while search results, the library and a game's
// details load. Each one is announced once and sized like the content it stands in for.

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DetailSkeleton, LibrarySkeleton, ResultsSkeleton } from "./Skeletons";
import type { GridShape } from "./library/VirtualGrid";

afterEach(cleanup);

const SHAPE: GridShape = {
  minCardWidth: 168,
  gap: 20,
  rowGap: 28,
  captionHeight: 64,
  minColumns: 2,
};

describe("ResultsSkeleton", () => {
  it("shows the progress message as a live status", () => {
    render(<ResultsSkeleton message="Ranking the best matches…" />);
    expect(screen.getByRole("status").textContent).toContain("Ranking the best matches…");
  });

  it("draws one placeholder card per expected pick", () => {
    render(<ResultsSkeleton message="Reading your request…" count={5} />);
    expect(screen.getAllByTestId("result-skeleton-card")).toHaveLength(5);
  });

  it("hides the placeholder shapes from screen readers", () => {
    render(<ResultsSkeleton message="Reading your request…" />);
    const cards = screen.getAllByTestId("result-skeleton-card");
    expect(cards.every((card) => card.closest("[aria-hidden='true']"))).toBe(true);
  });
});

describe("LibrarySkeleton", () => {
  it("is announced as loading the library", () => {
    render(<LibrarySkeleton shape={SHAPE} />);
    expect(screen.getByRole("status", { name: "Loading your library…" })).toBeTruthy();
  });

  it("lays its cards out on the same grid as the real library", () => {
    render(<LibrarySkeleton shape={SHAPE} />);
    const grid = screen.getByTestId("library-skeleton-grid");
    expect(grid.style.columnGap).toBe("20px");
    expect(grid.style.rowGap).toBe("28px");
    expect(grid.style.gridTemplateColumns).toContain("168px");
  });

  it("gives each card a 2:3 cover and a caption exactly as tall as the real one", () => {
    render(<LibrarySkeleton shape={SHAPE} />);
    const cards = screen.getAllByTestId("library-skeleton-card");
    expect(cards.length).toBeGreaterThan(0);
    for (const card of cards) {
      expect(card.querySelector(".aspect-\\[2\\/3\\]")).toBeTruthy();
      expect((card.lastElementChild as HTMLElement).style.height).toBe("64px");
    }
  });
});

describe("DetailSkeleton", () => {
  it("is announced as loading the game's details", () => {
    render(<DetailSkeleton />);
    expect(screen.getByRole("status", { name: "Loading game details…" })).toBeTruthy();
  });
});

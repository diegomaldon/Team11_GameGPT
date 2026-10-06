// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { VirtualList, visibleRange } from "./VirtualList";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const ROW = 80;
const items = (n: number) => Array.from({ length: n }, (_, i) => `Game ${i + 1}`);

function renderList(n: number) {
  return render(
    <VirtualList
      items={items(n)}
      rowHeight={ROW}
      getKey={(s) => s}
      renderRow={(s) => <span>{s}</span>}
      label="Owned games"
    />,
  );
}

/** Pretend the page is scrolled so the list's top edge sits `px` above the viewport. */
function scrollListBy(px: number) {
  const list = screen.getByRole("list", { name: "Owned games" });
  vi.spyOn(list, "getBoundingClientRect").mockReturnValue({ top: -px } as DOMRect);
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
    cb(0);
    return 1;
  });
  act(() => {
    window.dispatchEvent(new Event("scroll"));
  });
}

describe("visibleRange", () => {
  it("covers the viewport plus overscan", () => {
    // List starts at the top of an 800px viewport: rows 0..10 visible.
    expect(visibleRange(0, 800, ROW, 5000, 8)).toEqual({ start: 0, end: 18 });
  });

  it("follows the scroll position", () => {
    // Scrolled 1000 rows down.
    expect(visibleRange(-1000 * ROW, 800, ROW, 5000, 8)).toEqual({ start: 992, end: 1018 });
  });

  it("never runs past either end of the list", () => {
    expect(visibleRange(-10_000 * ROW, 800, ROW, 50, 8)).toEqual({ start: 50, end: 50 });
    expect(visibleRange(2000, 800, ROW, 50, 8)).toEqual({ start: 0, end: 0 });
  });
});

describe("VirtualList (TM11-50 AC: renders 1000+ entries without freezing)", () => {
  it("puts only a window of 5,000 rows in the DOM", () => {
    renderList(5000);
    const rows = screen.getAllByRole("listitem");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(40);
    // The list is still the full height, so the scrollbar is honest.
    const list = screen.getByRole("list", { name: "Owned games" });
    expect(list.style.height).toBe(`${5000 * ROW}px`);
  });

  it("tells assistive tech each row's place in the whole list", () => {
    renderList(5000);
    const first = screen.getAllByRole("listitem")[0];
    expect(first.getAttribute("aria-setsize")).toBe("5000");
    expect(first.getAttribute("aria-posinset")).toBe("1");
  });

  it("swaps in the rows that scroll into view", () => {
    renderList(5000);
    expect(screen.queryByText("Game 2001")).toBeNull();

    scrollListBy(2000 * ROW);

    expect(screen.getByText("Game 2001")).toBeTruthy();
    expect(screen.queryByText("Game 1")).toBeNull();
    expect(screen.getAllByRole("listitem").length).toBeLessThan(40);
  });

  it("places each row at its own offset", () => {
    renderList(5000);
    scrollListBy(2000 * ROW);
    const row = screen.getByText("Game 2001").closest("li")!;
    expect(row.style.top).toBe(`${2000 * ROW}px`);
  });

  it("renders a short list in full", () => {
    renderList(5);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
  });
});

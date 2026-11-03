"use client";

// Window-scrolled virtual grid of cover cards (TM11-142), the grid form of VirtualList.
//
// The library shows each game as a cover card in as many columns as fit. A Steam
// library can run to thousands of titles, so, as in VirtualList, only the rows near
// the viewport are in the DOM. Every card is still its own list item, positioned by
// row and column, with aria-posinset/aria-setsize so assistive tech hears the whole list.
//
// Card width follows the list's measured width; a row's height is the card's 2:3 cover
// plus a fixed caption, so the row math stays exact.

import { useLayoutEffect, useRef, useState } from "react";
import { visibleRange } from "./VirtualList";

type Range = { start: number; end: number };

/** Rows rendered before the first measurement, so the first paint isn't empty. */
const INITIAL_ROWS = 6;
/** Height used until the list has been measured (and in tests, where nothing is). */
const FALLBACK_ROW_HEIGHT = 320;

export type GridMetrics = { columns: number; cardWidth: number; rowHeight: number };

/** How many cards fit across `width`, how wide each is, and how tall a row is. */
export function gridMetrics(
  width: number,
  { minCardWidth, gap, rowGap, captionHeight, minColumns }: GridShape,
): GridMetrics {
  if (width <= 0) {
    return { columns: minColumns, cardWidth: 0, rowHeight: FALLBACK_ROW_HEIGHT };
  }
  const columns = Math.max(minColumns, Math.floor((width + gap) / (minCardWidth + gap)));
  const cardWidth = (width - gap * (columns - 1)) / columns;
  return { columns, cardWidth, rowHeight: Math.round(cardWidth * 1.5 + captionHeight + rowGap) };
}

export type GridShape = {
  minCardWidth: number;
  /** Space between columns, px. */
  gap: number;
  /** Space between rows, px. */
  rowGap: number;
  /** Height of everything under the cover, px. Cards must render exactly this. */
  captionHeight: number;
  minColumns: number;
};

export function VirtualGrid<T>({
  items,
  shape,
  getKey,
  renderCard,
  overscan = 3,
  label,
}: {
  items: T[];
  shape: GridShape;
  getKey: (item: T) => string;
  renderCard: (item: T) => React.ReactNode;
  overscan?: number;
  label: string;
}) {
  const ref = useRef<HTMLUListElement>(null);
  const [width, setWidth] = useState(0);
  const { columns, rowHeight } = gridMetrics(width, shape);
  const rowCount = Math.ceil(items.length / columns);
  const [range, setRange] = useState<Range>({
    start: 0,
    end: Math.min(rowCount, INITIAL_ROWS),
  });

  // Track the list's width so the column count follows the window.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Which rows are near the viewport. Same scheduling as VirtualList.
  useLayoutEffect(() => {
    const update = () => {
      const el = ref.current;
      if (!el) return;
      const next = visibleRange(
        el.getBoundingClientRect().top,
        window.innerHeight,
        rowHeight,
        rowCount,
        overscan,
      );
      setRange((prev) => (prev.start === next.start && prev.end === next.end ? prev : next));
    };
    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        update();
      });
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [rowCount, rowHeight, overscan]);

  const gutters = shape.gap * (columns - 1);
  const cardWidth = `calc((100% - ${gutters}px) / ${columns})`;
  const cards = [];
  const first = range.start * columns;
  const last = Math.min(items.length, Math.min(range.end, rowCount) * columns);
  for (let i = first; i < last; i++) {
    const row = Math.floor(i / columns);
    const col = i % columns;
    cards.push(
      <li
        key={getKey(items[i])}
        aria-setsize={items.length}
        aria-posinset={i + 1}
        className="absolute"
        style={{
          top: row * rowHeight,
          left: `calc(${col} * (${cardWidth} + ${shape.gap}px))`,
          width: cardWidth,
          height: rowHeight - shape.rowGap,
        }}
      >
        {renderCard(items[i])}
      </li>,
    );
  }

  return (
    <ul
      ref={ref}
      aria-label={label}
      className="relative"
      style={{ height: rowCount * rowHeight }}
    >
      {cards}
    </ul>
  );
}

"use client";

// Window-scrolled virtual list (TM11-50).
//
// A Steam library can run to thousands of titles. Rendering every row means
// thousands of DOM nodes on mount and on every filter change, which is what
// freezes the page. This renders only the rows near the viewport, so 5,000
// games cost about the same as 20.
//
// The page scrolls on the window (AppShell has no inner scroll container), so
// the list follows window scroll rather than owning a scrollbox. Rows have a
// fixed height, which keeps the math exact: row i sits at i * rowHeight.

import { useEffect, useRef, useState } from "react";

type Range = { start: number; end: number };

/** Rows rendered before the first measurement, so the first paint isn't empty. */
const INITIAL_ROWS = 24;

export function visibleRange(
  listTop: number,
  viewportHeight: number,
  rowHeight: number,
  count: number,
  overscan: number,
): Range {
  const first = Math.floor(-listTop / rowHeight);
  const last = Math.ceil((viewportHeight - listTop) / rowHeight);
  const start = Math.min(count, Math.max(0, first - overscan));
  const end = Math.min(count, Math.max(start, last + overscan));
  return { start, end };
}

export function VirtualList<T>({
  items,
  rowHeight,
  getKey,
  renderRow,
  overscan = 8,
  label,
}: {
  items: T[];
  /** Height of one row in px, including any gap below it. */
  rowHeight: number;
  getKey: (item: T) => string;
  renderRow: (item: T) => React.ReactNode;
  overscan?: number;
  label: string;
}) {
  const ref = useRef<HTMLUListElement>(null);
  const [range, setRange] = useState<Range>({
    start: 0,
    end: Math.min(items.length, INITIAL_ROWS),
  });

  useEffect(() => {
    const update = () => {
      const el = ref.current;
      if (!el) return;
      const next = visibleRange(
        el.getBoundingClientRect().top,
        window.innerHeight,
        rowHeight,
        items.length,
        overscan,
      );
      setRange((prev) =>
        prev.start === next.start && prev.end === next.end ? prev : next,
      );
    };

    // One measurement per frame, however fast the scroll events arrive.
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
  }, [items.length, rowHeight, overscan]);

  const rows = [];
  for (let i = range.start; i < Math.min(range.end, items.length); i++) {
    const item = items[i];
    rows.push(
      <li
        key={getKey(item)}
        // Only a window of rows is in the DOM, so tell assistive tech where
        // this one sits in the whole list.
        aria-setsize={items.length}
        aria-posinset={i + 1}
        className="absolute inset-x-0"
        style={{ top: i * rowHeight, height: rowHeight }}
      >
        {renderRow(item)}
      </li>,
    );
  }

  return (
    <ul
      ref={ref}
      aria-label={label}
      className="relative"
      style={{ height: items.length * rowHeight }}
    >
      {rows}
    </ul>
  );
}

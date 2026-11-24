// Loading placeholders for the async surfaces: search results, the library and a
// game's details (TM11-76, REQ040).
//
// Each placeholder copies the box sizes of the content it stands in for, so nothing
// jumps when the content arrives. The shapes are aria-hidden; one status line says
// what is loading. The shimmer stops under prefers-reduced-motion (globals.css).

import { useId } from "react";
import type { GridShape } from "./library/VirtualGrid";
import { cx } from "./ui";

const BLOCK = "rounded bg-[var(--raised-2)]";

/** Placeholder picks while a search runs, with the progress message in the heading's place. */
export function ResultsSkeleton({ message, count = 3 }: { message: string; count?: number }) {
  return (
    <div>
      {/* Same classes as the "N picks for your vibe" heading, so the cards start where the
          real ones will. */}
      <p role="status" className="mb-5 font-display text-[28px] text-[var(--ink-faint)]">
        {message}
      </p>
      <ul aria-hidden="true" className="flex flex-col gap-4">
        {Array.from({ length: count }, (_, i) => (
          <li
            key={i}
            data-testid="result-skeleton-card"
            className={cx(
              "shimmer flex gap-5 rounded-3xl border border-[var(--border)]",
              "bg-[var(--surface)] p-5",
            )}
          >
            <div className={`h-[126px] w-[84px] shrink-0 rounded-xl ${BLOCK}`} />
            {/* Title line, two lines of explanation, then the 44px action row. */}
            <div className="min-w-0 flex-1">
              <div className={`h-[30px] w-1/3 ${BLOCK}`} />
              <div className="mt-2 space-y-2 py-1">
                <div className={`h-4 w-full ${BLOCK}`} />
                <div className={`h-4 w-4/5 ${BLOCK}`} />
              </div>
              <div className="mt-3 flex h-11 items-center justify-between">
                <div className={`h-4 w-28 ${BLOCK}`} />
                <div className="flex gap-1.5">
                  <div className={`h-11 w-11 rounded-full ${BLOCK}`} />
                  <div className={`h-11 w-11 rounded-full ${BLOCK}`} />
                </div>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Placeholder library: the toolbar's three controls, then cover cards on the same grid
 * as VirtualGrid. CSS `auto-fill` with `minmax(minCardWidth, 1fr)` gives the same column
 * count as gridMetrics(), and the inner `min()` keeps at least `minColumns`.
 */
export function LibrarySkeleton({ shape, count = 12 }: { shape: GridShape; count?: number }) {
  const labelId = useId();
  const { minCardWidth, gap, rowGap, captionHeight, minColumns } = shape;
  const narrowestCard = `calc((100% - ${gap * (minColumns - 1)}px) / ${minColumns})`;
  const cardWidth = `minmax(min(${minCardWidth}px, ${narrowestCard}), 1fr)`;
  return (
    <div role="status" aria-labelledby={labelId}>
      <span id={labelId} className="sr-only">
        Loading your library…
      </span>
      <div aria-hidden="true">
        {/* The platform pills are 50px with their border and padding. min-h keeps the search
            box from collapsing to nothing under flex-1 when the toolbar stacks on phones. */}
        <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className={`h-[50px] w-72 max-w-full self-start rounded-full ${BLOCK}`} />
          <div className={`h-12 min-h-12 flex-1 rounded-full ${BLOCK}`} />
          <div className={`h-12 rounded-full lg:w-52 ${BLOCK}`} />
        </div>
        <div
          data-testid="library-skeleton-grid"
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(auto-fill, ${cardWidth})`,
            columnGap: `${gap}px`,
            rowGap: `${rowGap}px`,
          }}
        >
          {Array.from({ length: count }, (_, i) => (
            <div key={i} data-testid="library-skeleton-card" className="flex flex-col">
              <div
                className={cx(
                  "shimmer aspect-[2/3] w-full rounded-[18px] border border-[var(--border)]",
                  BLOCK,
                )}
              />
              <div
                style={{ height: `${captionHeight}px` }}
                className="flex flex-col justify-center gap-2"
              >
                <div className={`h-4 w-3/4 ${BLOCK}`} />
                <div className={`h-3 w-1/2 ${BLOCK}`} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * Placeholder for the game detail panel (TM11-78): cover, title, tag pills and a
 * description. Match these boxes to the panel's when it lands.
 */
export function DetailSkeleton() {
  const labelId = useId();
  return (
    <div role="status" aria-labelledby={labelId}>
      <span id={labelId} className="sr-only">
        Loading game details…
      </span>
      <div aria-hidden="true" className="shimmer flex flex-col gap-6 sm:flex-row">
        <div className={`aspect-[2/3] w-40 shrink-0 rounded-[18px] ${BLOCK}`} />
        <div className="min-w-0 flex-1">
          <div className={`h-9 w-2/3 ${BLOCK}`} />
          <div className="mt-4 flex gap-2">
            <div className={`h-7 w-20 rounded-full ${BLOCK}`} />
            <div className={`h-7 w-24 rounded-full ${BLOCK}`} />
            <div className={`h-7 w-16 rounded-full ${BLOCK}`} />
          </div>
          <div className="mt-5 space-y-2.5">
            <div className={`h-4 w-full ${BLOCK}`} />
            <div className={`h-4 w-full ${BLOCK}`} />
            <div className={`h-4 w-3/5 ${BLOCK}`} />
          </div>
        </div>
      </div>
    </div>
  );
}

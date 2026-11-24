"use client";

// The player's last few searches on Discover, each with the games it returned
// (TM11-78 AC2: the detail panel is reachable from history). Any of those games
// opens the detail panel. Reads GET /api/history (TM11-64), and reloads after each
// new search so the one just made shows up.
//
// This is the minimal history surface; TM11-84 grows it into the full history page
// (and TM11-85/87 add paging, filters and re-running a query). A failed read shows
// TM11-77's "history temporarily unavailable" panel with a retry.

import { useEffect, useState } from "react";
import { getHistory } from "@/lib/api/client";
import type { HistoryEntry } from "@/lib/api/types";
import { describeFailure, type FailureState } from "@/lib/api/failureState";
import { targetFromHistory, type DetailTarget } from "@/lib/discover/gameDetail";
import { ServiceError } from "@/components/ServiceError";

/** How many past searches Discover shows. */
export const RECENT_SEARCH_LIMIT = 3;

type Load =
  | { status: "loading" }
  | { status: "ready"; items: HistoryEntry[] }
  | { status: "failed"; failure: FailureState };

const searchedOn = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
});

export function RecentSearches({
  refreshKey,
  onOpen,
}: {
  /** Changes after each search, so the list reloads. */
  refreshKey: number;
  onOpen: (target: DetailTarget, opener: HTMLElement) => void;
}) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getHistory(RECENT_SEARCH_LIMIT).then(
      (res) => !cancelled && setLoad({ status: "ready", items: res.items }),
      (err: unknown) =>
        !cancelled && setLoad({ status: "failed", failure: describeFailure(err, "history") }),
    );
    return () => {
      cancelled = true;
    };
  }, [refreshKey, attempt]);

  return (
    <section aria-labelledby="recent-searches-heading" className="mx-auto mt-16 max-w-[880px]">
      <h2 id="recent-searches-heading" className="mb-4 font-display text-[28px]">
        Recent searches
      </h2>

      {load.status === "loading" && (
        <p role="status" className="text-sm text-[var(--ink-faint)]">
          Loading your recent searches…
        </p>
      )}

      {load.status === "failed" && (
        <ServiceError failure={load.failure} onRetry={() => setAttempt((n) => n + 1)} />
      )}

      {load.status === "ready" && load.items.length === 0 && (
        <p className="text-sm text-[var(--ink-faint)]">
          Your past searches will show up here, with the games they found.
        </p>
      )}

      {load.status === "ready" && load.items.length > 0 && (
        <ul className="flex flex-col gap-3">
          {load.items.map((entry) => {
            const games = entry.recommendations ?? [];
            return (
              <li
                key={entry.query_id}
                data-testid="recent-search"
                className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <q className="min-w-0 break-words text-[15px] font-semibold text-[var(--ink)]">
                    {entry.query}
                  </q>
                  <time
                    dateTime={entry.created_at}
                    className="shrink-0 text-[13px] text-[var(--ink-faint)]"
                  >
                    {searchedOn.format(new Date(entry.created_at))}
                  </time>
                </div>
                {games.length > 0 ? (
                  <ul
                    aria-label={`Games found for "${entry.query}"`}
                    className="mt-2 flex flex-wrap gap-x-1 gap-y-1"
                  >
                    {games.map((rec) => (
                      <li key={`${rec.rank}-${rec.title}`}>
                        <button
                          type="button"
                          aria-haspopup="dialog"
                          onClick={(e) => onOpen(targetFromHistory(rec), e.currentTarget)}
                          className="min-h-11 rounded-full px-3 text-left text-sm font-medium text-[var(--heading)] underline-offset-4 hover:underline"
                        >
                          {rec.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-sm text-[var(--ink-faint)]">
                    No games were saved for this search.
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

"use client";

// Library: one list of everything the user owns, across platforms (TM11-50).
//
// Every owned game comes from GET /api/library, including games added by hand
// (TM11-54, AddGameModal). Games added by hand before TM11-54 still live in the
// mock store and are shown too. lib/library/unified.ts merges them so a game
// owned on two platforms is one row with two badges, and VirtualList keeps a
// 1000+ game library smooth.
//
// TM11-51: sort by title or playtime and search by title, both client-side (see
// lib/library/view.ts for why). The view is saved per tab, so leaving the page
// and coming back keeps the sort, search and platform filter.
//
// TM11-60: Refresh re-syncs every linked platform (lib/library/useLibraryRefresh.ts)
// and the list is read again in place when it finishes.
//
// TM11-142: games show as cover cards in a virtual grid (VirtualGrid), with Steam art
// where there is an app id and an initials tile otherwise.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMock } from "@/lib/mock/store";
import {
  GAME_PLATFORM_LABEL,
  PLATFORMS,
  type GamePlatform,
} from "@/lib/mock/data";
import { getLibrary } from "@/lib/api/client";
import { useLibraryRefresh } from "@/lib/library/useLibraryRefresh";
import type { LibraryItem } from "@/lib/api/types";
import {
  countByPlatform,
  formatPlaytime,
  mergeLibrary,
  type UnifiedGame,
} from "@/lib/library/unified";
import {
  DEFAULT_VIEW,
  loadView,
  saveView,
  searchRows,
  SORT_OPTIONS,
  sortRows,
  type LibrarySort,
  type LibraryView,
  type PlatformFilter,
} from "@/lib/library/view";
import { AddGameModal } from "@/components/library/AddGameModal";
import { CsvImportModal } from "@/components/library/CsvImportModal";
import { RefreshStatus } from "@/components/library/RefreshStatus";
import { VirtualGrid, type GridShape } from "@/components/library/VirtualGrid";
import { GameArt } from "@/components/discover/GameArt";
import { Button, PageHeader, Select, TextInput, cx } from "@/components/ui";
import {
  Check,
  Library as LibraryIcon,
  Plus,
  Search,
  Spinner,
  Trash,
  X,
} from "@/components/icons";

const FILTERS: { key: PlatformFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "steam", label: "Steam" },
  { key: "xbox", label: "Xbox" },
  { key: "epic", label: "Epic" },
  { key: "playstation", label: "PlayStation" },
  { key: "other", label: "Other" },
];

/** Cover card sizes. GameCard's caption must be exactly captionHeight tall. */
const GRID_SHAPE: GridShape = {
  minCardWidth: 168,
  gap: 20,
  rowGap: 28,
  captionHeight: 64,
  minColumns: 2,
};

type Remote =
  | { status: "loading" }
  | { status: "ready"; items: LibraryItem[] }
  | { status: "error" };

function PlatformTag({ platform }: { platform: GamePlatform }) {
  const label = GAME_PLATFORM_LABEL[platform];
  const Icon = platform === "other" ? null : PLATFORMS[platform].Icon;
  return (
    <span
      title={label}
      className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[var(--border-strong)] px-1.5 py-0.5 text-[11px] font-semibold text-[var(--label)]"
    >
      {Icon && <Icon className="h-3.5 w-3.5" aria-hidden="true" />}
      {/* Icon-only on cards, so several badges fit beside the playtime. */}
      <span className={Icon ? "sr-only" : undefined}>{label}</span>
    </span>
  );
}

export default function LibraryPage() {
  const { state, hydrated, removeGame } = useMock();
  const [remote, setRemote] = useState<Remote>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  // The server render has no sessionStorage; it only ever shows the loading
  // state, so starting it from the default can't cause a hydration mismatch.
  const [view, setView] = useState<LibraryView>(() =>
    typeof window === "undefined" ? DEFAULT_VIEW : loadView(),
  );
  const [open, setOpen] = useState(false);
  const [isCsvOpen, setIsCsvOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getLibrary().then(
      (res) => live && setRemote({ status: "ready", items: res.items }),
      // A failed re-read after a refresh keeps the list already on screen.
      () => live && setRemote((prev) => (prev.status === "ready" ? prev : { status: "error" })),
    );
    return () => {
      live = false;
    };
  }, [attempt]);

  useEffect(() => saveView(view), [view]);

  const readLibraryAgain = useCallback(() => setAttempt((n) => n + 1), []);
  const refresh = useLibraryRefresh(readLibraryAgain);

  function updateView(patch: Partial<LibraryView>) {
    setView((prev) => ({ ...prev, ...patch }));
  }

  const rows = useMemo(
    () => mergeLibrary(remote.status === "ready" ? remote.items : [], state.games),
    [remote, state.games],
  );
  const counts = useMemo(() => countByPlatform(rows), [rows]);

  // Sorted once per sort change, so typing a search only filters.
  const sorted = useMemo(() => sortRows(rows, view.sort), [rows, view.sort]);

  // A filter whose last game was just removed falls back to All.
  const filter = view.platform;
  const active = filter !== "all" && counts[filter] === 0 ? "all" : filter;
  const shown = useMemo(() => {
    const onPlatform =
      active === "all" ? sorted : sorted.filter((r) => r.platforms.includes(active));
    return searchRows(onPlatform, view.query);
  }, [sorted, active, view.query]);
  const searching = view.query.trim() !== "";

  const loading = !hydrated || remote.status === "loading";
  const failed = remote.status === "error";

  function flash(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2500);
  }

  function retry() {
    setRemote({ status: "loading" });
    setAttempt((n) => n + 1);
  }

  function remove(row: UnifiedGame) {
    row.manualIds.forEach((id) => removeGame(id));
    flash(`Removed ${row.title}`);
  }

  return (
    <>
      <PageHeader
        title="Your library"
        subtitle="Games you own across platforms. Owned games are skipped in recommendations."
        action={
          <div className="flex shrink-0 gap-2">
            {refresh.canRefresh && (
              <Button
                size="sm"
                variant="secondary"
                onClick={refresh.refresh}
                disabled={refresh.refreshing}
              >
                {refresh.refreshing ? (
                  <>
                    <Spinner className="h-4 w-4" />
                    Refreshing…
                  </>
                ) : (
                  "Refresh"
                )}
              </Button>
            )}
            <Button size="sm" variant="secondary" onClick={() => setIsCsvOpen(true)}>
              Import CSV
            </Button>
            <Button size="sm" onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" />
              Add game
            </Button>
          </div>
        }
      />

      <RefreshStatus refresh={refresh} />

      {toast && (
        <div
          role="status"
          className="mb-4 inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-4 py-2 text-[13px] font-medium text-emerald-700"
        >
          <Check className="h-4 w-4" />
          {toast}
        </div>
      )}

      {failed && (
        <div
          role="alert"
          className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-5 py-3 text-[13px] text-rose-700"
        >
          <span>
            Couldn&apos;t load your imported games.
            {state.games.length > 0 && " Games you added by hand are still shown."}
          </span>
          <Button size="sm" variant="secondary" onClick={retry}>
            Try again
          </Button>
        </div>
      )}

      {loading ? (
        <div
          role="status"
          className="flex items-center justify-center gap-2 rounded-3xl border border-[var(--border)] bg-[var(--surface)] px-6 py-14 text-sm text-[var(--ink-faint)]"
        >
          <Spinner className="h-4 w-4" />
          Loading your library…
        </div>
      ) : rows.length === 0 ? (
        // A failed load is not an empty library: the banner above says so,
        // and telling the user to link a platform they may have linked is wrong.
        !failed && <EmptyLibrary onAdd={() => setOpen(true)} />
      ) : (
        <>
          <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center">
            {/* Filters */}
            <div
              role="group"
              aria-label="Platform"
              className="flex flex-wrap gap-1 self-start rounded-full border border-[var(--border)] bg-[var(--surface)] p-1"
            >
              {FILTERS.map((f) => {
                const count = f.key === "all" ? rows.length : counts[f.key];
                if (f.key !== "all" && count === 0) return null;
                const on = active === f.key;
                return (
                  <button
                    key={f.key}
                    type="button"
                    aria-pressed={on}
                    onClick={() => updateView({ platform: f.key })}
                    className={cx(
                      "min-h-10 rounded-full px-4 text-sm font-medium transition-colors",
                      on
                        ? "bg-[var(--raised-2)] text-[var(--heading)]"
                        : "text-[var(--ink-faint)] hover:text-[var(--heading)]",
                    )}
                  >
                    {f.label}
                    <span className="ml-1.5 opacity-70">{count.toLocaleString("en-US")}</span>
                  </button>
                );
              })}
            </div>
            <div className="relative flex-1">
              <label htmlFor="library-search" className="sr-only">
                Search your library
              </label>
              <Search
                className={cx(
                  "pointer-events-none absolute left-5 top-1/2 h-4 w-4 -translate-y-1/2",
                  "text-[var(--ink-faint)]",
                )}
                aria-hidden="true"
              />
              <TextInput
                id="library-search"
                type="search"
                placeholder="Search by title"
                autoComplete="off"
                value={view.query}
                onChange={(e) => updateView({ query: e.target.value })}
                className="pl-12 pr-12 [&::-webkit-search-cancel-button]:hidden"
              />
              {view.query && (
                <button
                  type="button"
                  onClick={() => updateView({ query: "" })}
                  aria-label="Clear search"
                  className={cx(
                    "absolute right-2 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center",
                    "justify-center rounded-full text-[var(--ink-faint)] hover:bg-[var(--raised-2)]",
                  )}
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
            <div className="lg:w-52">
              <label htmlFor="library-sort" className="sr-only">
                Sort by
              </label>
              <Select
                id="library-sort"
                value={view.sort}
                onChange={(e) => updateView({ sort: e.target.value as LibrarySort })}
              >
                {SORT_OPTIONS.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {searching && (
            <p role="status" className="mb-3 text-[13px] text-[var(--ink-faint)]">
              {shown.length === 0
                ? `No games match “${view.query.trim()}”.`
                : `${shown.length.toLocaleString("en-US")} ${matchNoun(shown.length)}`}
            </p>
          )}

          <VirtualGrid
            items={shown}
            shape={GRID_SHAPE}
            getKey={(r) => r.key}
            label="Owned games"
            renderCard={(r) => <GameCard row={r} onRemove={() => remove(r)} />}
          />
        </>
      )}

      <AddGameModal
        open={open}
        onClose={() => setOpen(false)}
        onAdded={(game) => {
          setOpen(false);
          flash(`Added ${game.title}`);
          retry();
        }}
      />

      {/* TM11-55: the modal owns the whole upload; the page only reloads after. */}
      <CsvImportModal
        open={isCsvOpen}
        onClose={() => setIsCsvOpen(false)}
        onImported={(result) => {
          if (result.added > 0) {
            retry();
          }
        }}
      />
    </>
  );
}

function matchNoun(count: number): string {
  return count === 1 ? "game matches" : "games match";
}

function GameCard({ row, onRemove }: { row: UnifiedGame; onRemove: () => void }) {
  const playtime = row.imported
    ? (formatPlaytime(row.playtimeMinutes) ?? "Not played yet")
    : null;
  return (
    <div className="group flex h-full flex-col">
      <div className="relative aspect-[2/3] w-full overflow-hidden rounded-[18px] border border-[var(--border)] bg-[var(--raised-2)]">
        <GameArt appId={row.appid} title={row.title} sizes="(min-width: 640px) 200px, 45vw" decorative />
      </div>
      {/* Exactly GRID_SHAPE.captionHeight tall: VirtualGrid's row maths depends on it.
          The remove button sits here, not on the cover, so it never hides the art. */}
      <div className="flex h-16 items-center gap-1.5 overflow-hidden">
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <p className="truncate text-[15px] font-medium text-[var(--ink)]">{row.title}</p>
          <div className="flex items-center gap-2 text-[13px] text-[var(--ink-faint)]">
            <span className="flex shrink-0 gap-1">
              {row.platforms.map((p) => (
                <PlatformTag key={p} platform={p} />
              ))}
            </span>
            <span className="truncate">{playtime}</span>
          </div>
        </div>
        {/* Imported copies come back on the next sync, so only hand-added ones can be removed. */}
        {row.manualIds.length > 0 && (
          <button
            type="button"
            onClick={onRemove}
            aria-label={row.imported ? `Remove hand-added ${row.title}` : `Remove ${row.title}`}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--ink-faint)] transition-colors hover:bg-rose-50 hover:text-rose-600"
          >
            <Trash className="h-[18px] w-[18px]" />
          </button>
        )}
      </div>
    </div>
  );
}

function EmptyLibrary({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex flex-col items-center rounded-3xl border border-dashed border-[var(--border-strong)] bg-[var(--surface)] px-6 py-16 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--raised-2)] text-[var(--ink-faint)]">
        <LibraryIcon className="h-5 w-5" />
      </span>
      <p className="mt-4 font-display text-2xl">Your library is empty</p>
      <p className="mt-2 max-w-sm text-sm text-[var(--ink-faint)]">
        Link a platform to import the games you own. GameGPT uses your library
        to skip games you already have.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Link
          href="/settings"
          className="inline-flex h-10 items-center justify-center gap-1.5 rounded-full bg-[var(--accent)] px-4 text-[13px] font-semibold text-[var(--on-accent)] transition-colors hover:bg-[var(--accent-hover)]"
        >
          Link a platform
        </Link>
        <Button size="sm" variant="secondary" onClick={onAdd}>
          <Plus className="h-4 w-4" />
          Add a game by hand
        </Button>
      </div>
    </div>
  );
}

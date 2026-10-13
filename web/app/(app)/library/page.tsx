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

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMock } from "@/lib/mock/store";
import {
  GAME_PLATFORM_LABEL,
  PLATFORMS,
  type GamePlatform,
} from "@/lib/mock/data";
import { getLibrary } from "@/lib/api/client";
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
import { VirtualList } from "@/components/library/VirtualList";
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

/** One row is 72px tall plus an 8px gap. VirtualList needs it fixed. */
const ROW_HEIGHT = 80;

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
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-semibold text-[var(--ink-soft)]"
    >
      {Icon && <Icon className="h-3.5 w-3.5" aria-hidden="true" />}
      {/* Icon-only on phones so four badges still fit on one line. */}
      <span className={Icon ? "sr-only sm:not-sr-only" : undefined}>{label}</span>
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
      () => live && setRemote({ status: "error" }),
    );
    return () => {
      live = false;
    };
  }, [attempt]);

  useEffect(() => saveView(view), [view]);

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

      {toast && (
        <div
          role="status"
          className="mb-4 inline-flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[13px] font-medium text-emerald-700"
        >
          <Check className="h-4 w-4" />
          {toast}
        </div>
      )}

      {failed && (
        <div
          role="alert"
          className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-700"
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
          className="flex items-center justify-center gap-2 rounded-2xl border border-[var(--border)] bg-white/60 px-6 py-14 text-sm text-[var(--ink-faint)]"
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
          <div className="mb-4 flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <label htmlFor="library-search" className="sr-only">
                Search your library
              </label>
              <Search
                className={cx(
                  "pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2",
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
                className="pl-10 pr-10 [&::-webkit-search-cancel-button]:hidden"
              />
              {view.query && (
                <button
                  type="button"
                  onClick={() => updateView({ query: "" })}
                  aria-label="Clear search"
                  className={cx(
                    "absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center",
                    "justify-center rounded-lg text-[var(--ink-faint)] hover:bg-neutral-100",
                  )}
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
            <div className="sm:w-48">
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

          {/* Filters */}
          <div className="mb-5 flex flex-wrap gap-2">
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
                    "rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors",
                    on
                      ? "border-[var(--ink)] bg-[var(--ink)] text-white"
                      : "border-[var(--border)] bg-white text-[var(--ink-soft)] hover:border-neutral-300",
                  )}
                >
                  {f.label}
                  <span className={cx("ml-1.5", on ? "text-white/70" : "text-[var(--ink-faint)]")}>
                    {count.toLocaleString("en-US")}
                  </span>
                </button>
              );
            })}
          </div>

          {searching && (
            <p role="status" className="mb-3 text-[13px] text-[var(--ink-faint)]">
              {shown.length === 0
                ? `No games match “${view.query.trim()}”.`
                : `${shown.length.toLocaleString("en-US")} ${matchNoun(shown.length)}`}
            </p>
          )}

          <VirtualList
            items={shown}
            rowHeight={ROW_HEIGHT}
            getKey={(r) => r.key}
            label="Owned games"
            renderRow={(r) => <GameRow row={r} onRemove={() => remove(r)} />}
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

function GameRow({ row, onRemove }: { row: UnifiedGame; onRemove: () => void }) {
  const playtime = row.imported
    ? (formatPlaytime(row.playtimeMinutes) ?? "Not played yet")
    : null;
  return (
    <div className="flex h-[72px] items-center gap-3 rounded-2xl border border-[var(--border)] bg-white px-4 shadow-card">
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-neutral-100 font-display text-sm font-bold text-[var(--ink-soft)]">
        {row.title.slice(0, 2).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{row.title}</p>
        <div className="mt-1 flex items-center gap-1.5 overflow-hidden">
          {row.platforms.map((p) => (
            <PlatformTag key={p} platform={p} />
          ))}
          {playtime && (
            <span className="ml-1 shrink-0 text-xs text-[var(--ink-faint)]">{playtime}</span>
          )}
        </div>
      </div>
      {/* Imported copies come back on the next sync, so only hand-added ones can be removed. */}
      {row.manualIds.length > 0 && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={row.imported ? `Remove hand-added ${row.title}` : `Remove ${row.title}`}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[var(--ink-faint)] transition-colors hover:bg-rose-50 hover:text-rose-600"
        >
          <Trash className="h-[18px] w-[18px]" />
        </button>
      )}
    </div>
  );
}

function EmptyLibrary({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-[var(--border)] bg-white/60 px-6 py-14 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-neutral-100 text-[var(--ink-faint)]">
        <LibraryIcon className="h-5 w-5" />
      </span>
      <p className="mt-3 text-sm font-semibold">Your library is empty</p>
      <p className="mt-1 max-w-xs text-xs text-[var(--ink-faint)]">
        Link a platform to import the games you own. GameGPT uses your library
        to skip games you already have.
      </p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        <Link
          href="/settings"
          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-xl bg-[var(--ink)] px-3.5 text-[13px] font-semibold text-white transition-colors hover:bg-black"
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

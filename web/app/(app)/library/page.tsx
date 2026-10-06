"use client";

// Library: one list of everything the user owns, across platforms (TM11-50).
//
// Imported games come from GET /api/library; hand-added ones from the mock
// store. lib/library/unified.ts merges them so a game owned on two platforms is
// one row with two badges, and VirtualList keeps a 1000+ game library smooth.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMock } from "@/lib/mock/store";
import {
  CATALOG,
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
import { VirtualList } from "@/components/library/VirtualList";
import {
  Button,
  Field,
  Modal,
  PageHeader,
  Select,
  TextInput,
  cx,
} from "@/components/ui";
import { Check, Library as LibraryIcon, Plus, Spinner, Trash } from "@/components/icons";

const FILTERS: { key: "all" | GamePlatform; label: string }[] = [
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
  const { state, hydrated, addGame, removeGame } = useMock();
  const [remote, setRemote] = useState<Remote>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState<"all" | GamePlatform>("all");
  const [open, setOpen] = useState(false);
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

  const rows = useMemo(
    () => mergeLibrary(remote.status === "ready" ? remote.items : [], state.games),
    [remote, state.games],
  );
  const counts = useMemo(() => countByPlatform(rows), [rows]);

  // A filter whose last game was just removed falls back to All.
  const active = filter !== "all" && counts[filter] === 0 ? "all" : filter;
  const shown = useMemo(
    () => (active === "all" ? rows : rows.filter((r) => r.platforms.includes(active))),
    [rows, active],
  );

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
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" />
            Add game
          </Button>
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
                  onClick={() => setFilter(f.key)}
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
        onAdd={(game) => {
          addGame(game);
          setOpen(false);
          flash(`Added ${game.title}`);
        }}
      />
    </>
  );
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

function AddGameModal({
  open,
  onClose,
  onAdd,
}: {
  open: boolean;
  onClose: () => void;
  onAdd: (g: { title: string; platform: GamePlatform; appid?: number }) => void;
}) {
  const [title, setTitle] = useState("");
  const [platform, setPlatform] = useState<GamePlatform>("steam");
  const [appid, setAppid] = useState("");
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setTitle("");
    setPlatform("steam");
    setAppid("");
    setError(null);
  }

  function submit() {
    if (!title.trim()) {
      setError("Enter a game title.");
      return;
    }
    onAdd({
      title: title.trim(),
      platform,
      appid: appid ? Number(appid) : undefined,
    });
    reset();
  }

  const suggestions = title
    ? CATALOG.filter(
        (c) =>
          c.title.toLowerCase().includes(title.toLowerCase()) &&
          c.title.toLowerCase() !== title.toLowerCase(),
      ).slice(0, 4)
    : [];

  return (
    <Modal
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Add a game"
      footer={
        <>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              reset();
              onClose();
            }}
          >
            Cancel
          </Button>
          <Button size="sm" onClick={submit}>
            Add to library
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label="Title" htmlFor="game-title" error={error ?? undefined}>
          <TextInput
            id="game-title"
            placeholder="Start typing a game name…"
            value={title}
            autoFocus
            onChange={(e) => {
              setTitle(e.target.value);
              setError(null);
            }}
          />
        </Field>

        {suggestions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button
                key={s.title}
                type="button"
                onClick={() => {
                  setTitle(s.title);
                  if (s.appid) setAppid(String(s.appid));
                }}
                className="rounded-full border border-[var(--border)] bg-white px-3 py-1 text-[13px] text-[var(--ink-soft)] hover:border-accent-200 hover:bg-accent-50 hover:text-accent-700"
              >
                {s.title}
              </button>
            ))}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label="Platform" htmlFor="game-platform">
            <Select
              id="game-platform"
              value={platform}
              onChange={(e) => setPlatform(e.target.value as GamePlatform)}
            >
              {(Object.keys(GAME_PLATFORM_LABEL) as GamePlatform[]).map((p) => (
                <option key={p} value={p}>
                  {GAME_PLATFORM_LABEL[p]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Steam AppID" htmlFor="game-appid" hint="Optional">
            <TextInput
              id="game-appid"
              inputMode="numeric"
              placeholder="e.g. 413150"
              value={appid}
              onChange={(e) => setAppid(e.target.value.replace(/\D/g, ""))}
            />
          </Field>
        </div>
      </div>
    </Modal>
  );
}

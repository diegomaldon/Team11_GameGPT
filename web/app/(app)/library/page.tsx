"use client";

import { useMemo, useState } from "react";
import { useMock } from "@/lib/mock/store";
import {
  CATALOG,
  GAME_PLATFORM_LABEL,
  PLATFORMS,
  type GamePlatform,
} from "@/lib/mock/data";
import {
  Badge,
  Button,
  Field,
  Modal,
  PageHeader,
  Select,
  TextInput,
  cx,
} from "@/components/ui";
import { Check, Library as LibraryIcon, Plus, Trash } from "@/components/icons";

const FILTERS: { key: "all" | GamePlatform; label: string }[] = [
  { key: "all", label: "All" },
  { key: "steam", label: "Steam" },
  { key: "xbox", label: "Xbox" },
  { key: "epic", label: "Epic" },
  { key: "playstation", label: "PlayStation" },
  { key: "other", label: "Other" },
];

function PlatformTag({ platform }: { platform: GamePlatform }) {
  if (platform === "other") {
    return <Badge>Other</Badge>;
  }
  const { Icon, label } = PLATFORMS[platform];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-semibold text-[var(--ink-soft)]">
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

export default function LibraryPage() {
  const { state, addGame, removeGame } = useMock();
  const [filter, setFilter] = useState<"all" | GamePlatform>("all");
  const [open, setOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const shown = useMemo(
    () =>
      filter === "all"
        ? state.games
        : state.games.filter((g) => g.platform === filter),
    [state.games, filter],
  );

  function flash(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2500);
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

      {/* Filters */}
      <div className="mb-5 flex flex-wrap gap-2">
        {FILTERS.map((f) => {
          const count =
            f.key === "all"
              ? state.games.length
              : state.games.filter((g) => g.platform === f.key).length;
          if (f.key !== "all" && count === 0) return null;
          const active = filter === f.key;
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cx(
                "rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors",
                active
                  ? "border-[var(--ink)] bg-[var(--ink)] text-white"
                  : "border-[var(--border)] bg-white text-[var(--ink-soft)] hover:border-neutral-300",
              )}
            >
              {f.label}
              <span className={cx("ml-1.5", active ? "text-white/70" : "text-[var(--ink-faint)]")}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Grid */}
      {shown.length === 0 ? (
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-[var(--border)] bg-white/60 px-6 py-14 text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-neutral-100 text-[var(--ink-faint)]">
            <LibraryIcon className="h-5 w-5" />
          </span>
          <p className="mt-3 text-sm font-semibold">Nothing here yet</p>
          <p className="mt-1 max-w-xs text-xs text-[var(--ink-faint)]">
            Add a game manually, or link a platform in Settings to import your
            library.
          </p>
          <Button size="sm" className="mt-4" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" />
            Add a game
          </Button>
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {shown.map((g) => (
            <li
              key={g.id}
              className="group flex items-center gap-3 rounded-2xl border border-[var(--border)] bg-white p-4 shadow-card"
            >
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-neutral-100 font-display text-sm font-bold text-[var(--ink-soft)]">
                {g.title.slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{g.title}</p>
                <div className="mt-1 flex items-center gap-2">
                  <PlatformTag platform={g.platform} />
                  {g.appid && (
                    <span className="text-xs text-[var(--ink-faint)]">
                      #{g.appid}
                    </span>
                  )}
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  removeGame(g.id);
                  flash(`Removed ${g.title}`);
                }}
                aria-label={`Remove ${g.title}`}
                className="flex h-9 w-9 items-center justify-center rounded-lg text-[var(--ink-faint)] transition-colors hover:bg-rose-50 hover:text-rose-600"
              >
                <Trash className="h-[18px] w-[18px]" />
              </button>
            </li>
          ))}
        </ul>
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

"use client";

// Add one game to the library by hand (TM11-54, REQ004).
//
// For platforms with no library API (Epic, and Xbox until its link ships).
// The title box searches the games catalogue as the user types; only a game
// picked from those suggestions can be added, so every manual entry joins to a
// games row and ownership filtering works on it. The server stores it with
// import_method MANUAL and refuses a game already owned on that platform
// (api/services/manual_import.py).

import { useEffect, useId, useState } from "react";
import { ApiError, addManualGame, searchGames } from "@/lib/api/client";
import type { GameSearchResult, ManualAddResponse, ManualPlatform } from "@/lib/api/types";
import { Button, Field, Modal, Select, TextInput, cx } from "@/components/ui";
import { Spinner } from "@/components/icons";

const PLATFORM_OPTIONS: { value: ManualPlatform; label: string }[] = [
  { value: "epic", label: "Epic Games" },
  { value: "xbox", label: "Xbox" },
];

/** Same as the API's GAME_SEARCH_MIN_LENGTH: shorter queries return nothing. */
const MIN_QUERY = 2;
/** Wait for a pause in typing, so a fast typist sends one search, not ten. */
export const SEARCH_DEBOUNCE_MS = 250;

const FALLBACK_ERROR = "Something went wrong. Nothing was changed.";

/** Used when the server sent no message of its own (api/routers/library_manual.py). */
const ADD_ERROR: Record<number, string> = {
  404: "That game isn't in the catalogue. Pick one from the suggestions.",
  409: "That game is already in your library on this platform.",
};

type Search =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; items: GameSearchResult[] }
  | { status: "error" };

export function AddGameModal({
  open,
  onClose,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  onAdded: (game: ManualAddResponse) => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<GameSearchResult | null>(null);
  const [platform, setPlatform] = useState<ManualPlatform>("epic");
  const [search, setSearch] = useState<Search>({ status: "idle" });
  const [highlight, setHighlight] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const listId = useId();

  const text = query.trim();
  // Once a suggestion is picked the box shows its title; don't search for it again.
  const shouldSearch = open && !selected && text.length >= MIN_QUERY;

  useEffect(() => {
    if (!shouldSearch) {
      setSearch({ status: "idle" });
      return;
    }
    setSearch({ status: "loading" });
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      searchGames(text, { signal: controller.signal }).then(
        (res) => {
          setSearch({ status: "ready", items: res.items });
          setHighlight(res.items.length > 0 ? 0 : -1);
        },
        (err: unknown) => {
          if (!controller.signal.aborted && !(err instanceof DOMException)) {
            setSearch({ status: "error" });
          }
        },
      );
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [shouldSearch, text]);

  const suggestions = search.status === "ready" ? search.items : [];
  const isListOpen = !selected && search.status !== "idle";

  function close() {
    setQuery("");
    setSelected(null);
    setPlatform("epic");
    setHighlight(-1);
    setError(null);
    onClose();
  }

  function pick(game: GameSearchResult) {
    setSelected(game);
    setQuery(game.title);
    setError(null);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!isListOpen || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((i) => (i + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (e.key === "Enter" && highlight >= 0) {
      e.preventDefault();
      pick(suggestions[highlight]);
    }
  }

  async function submit() {
    if (!selected) {
      setError(text ? "Pick a game from the suggestions." : "Enter a game title.");
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const added = await addManualGame(platform, selected.game_id);
      onAdded(added);
      close();
    } catch (err) {
      setError(
        (err instanceof ApiError && (err.userMessage ?? ADD_ERROR[err.status])) || FALLBACK_ERROR,
      );
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Add a game"
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={close}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => void submit()} loading={isBusy}>
            Add to library
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field
          label="Title"
          htmlFor="game-title"
          error={error ?? undefined}
          hint="Pick the game from the list so it matches our catalogue."
        >
          <div className="relative">
            <TextInput
              id="game-title"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={isListOpen}
              aria-controls={listId}
              aria-activedescendant={
                isListOpen && highlight >= 0 ? `${listId}-${highlight}` : undefined
              }
              autoComplete="off"
              placeholder="Start typing a game name…"
              value={query}
              autoFocus
              onKeyDown={onKeyDown}
              onChange={(e) => {
                setQuery(e.target.value);
                setSelected(null);
                setError(null);
              }}
            />
            {isListOpen && (
              <ul
                id={listId}
                role="listbox"
                aria-label="Matching games"
                className="absolute inset-x-0 top-full z-10 mt-1 max-h-60 overflow-auto rounded-xl border border-[var(--border)] bg-white py-1 shadow-lift"
              >
                {search.status === "loading" && (
                  <li className="flex items-center gap-2 px-3.5 py-2 text-[13px] text-[var(--ink-faint)]">
                    <Spinner className="h-4 w-4" />
                    Searching…
                  </li>
                )}
                {search.status === "error" && (
                  <li className="px-3.5 py-2 text-[13px] text-rose-600">
                    Couldn&apos;t search right now. Try again in a moment.
                  </li>
                )}
                {search.status === "ready" && suggestions.length === 0 && (
                  <li className="px-3.5 py-2 text-[13px] text-[var(--ink-faint)]">
                    No games found. Check the spelling, or import a CSV to queue it for review.
                  </li>
                )}
                {suggestions.map((game, i) => (
                  <li
                    key={game.game_id}
                    id={`${listId}-${i}`}
                    role="option"
                    aria-selected={i === highlight}
                    // mousedown, not click: the input would blur first and the
                    // pick would race the list closing.
                    onMouseDown={(e) => {
                      e.preventDefault();
                      pick(game);
                    }}
                    onMouseEnter={() => setHighlight(i)}
                    className={cx(
                      "cursor-pointer px-3.5 py-2 text-sm",
                      i === highlight ? "bg-accent-50 text-accent-700" : "text-[var(--ink)]",
                    )}
                  >
                    {game.title}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Field>

        <Field label="Platform" htmlFor="game-platform" hint="Where you own this game.">
          <Select
            id="game-platform"
            value={platform}
            onChange={(e) => {
              setPlatform(e.target.value as ManualPlatform);
              setError(null);
            }}
          >
            {PLATFORM_OPTIONS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </Select>
        </Field>
      </div>
    </Modal>
  );
}

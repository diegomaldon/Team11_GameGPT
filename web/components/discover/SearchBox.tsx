"use client";

// The natural-language search on Discover (TM11-74, REQ011).
//
// Keyboard: Enter searches, Escape clears the field, and "/" anywhere on the page
// (outside another text field) jumps to it. The three example prompts fill the field
// rather than searching, so the player can tweak one first; focus moves to the field
// with the caret at the end so Enter is the next keystroke.

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { ArrowRight, Search, Spinner } from "@/components/icons";
import { EXAMPLE_PROMPTS } from "@/lib/discover/featured";

/** Matches RecommendRequest.query's max length in the API. */
export const MAX_QUERY_LENGTH = 500;

export type SearchBoxHandle = {
  /** Put `text` in the field and focus it, caret at the end. */
  fill: (text: string) => void;
};

/** True when the key press is already headed for something the user is typing in. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement
  );
}

export const SearchBox = forwardRef<
  SearchBoxHandle,
  {
    value: string;
    onChange: (value: string) => void;
    onSubmit: (value: string) => void;
    loading: boolean;
    placeholder: string;
  }
>(function SearchBox({ value, onChange, onSubmit, loading, placeholder }, ref) {
  const inputRef = useRef<HTMLInputElement>(null);

  function fill(text: string) {
    onChange(text);
    const input = inputRef.current;
    if (!input) return;
    input.focus();
    // After React has written the new value, so the caret lands after it.
    requestAnimationFrame(() => input.setSelectionRange(text.length, text.length));
  }

  useImperativeHandle(ref, () => ({ fill }));

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      // Not while a dialog (e.g. the game detail panel) is open: the field is behind
      // it, and a search from there would change the page under the dialog (TM11-78).
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      e.preventDefault();
      inputRef.current?.focus();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const canSubmit = !loading && value.trim().length > 0;

  return (
    <>
      <form
        role="search"
        aria-label="Find games"
        onSubmit={(e) => {
          e.preventDefault();
          // Enter while a search is running would otherwise start a second one.
          if (canSubmit) onSubmit(value);
        }}
        className="mt-8 flex items-center gap-2 rounded-full border border-[var(--border-input)] bg-[var(--surface)] p-2 pl-5 text-left focus-within:border-[var(--accent)] sm:pl-6"
      >
        <Search className="hidden h-5 w-5 shrink-0 text-[var(--ink-faint)] sm:block" />
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape" && value) {
              e.preventDefault();
              onChange("");
            }
          }}
          placeholder={placeholder}
          aria-label="Describe the game you want"
          aria-keyshortcuts="/"
          aria-describedby="search-hint"
          maxLength={MAX_QUERY_LENGTH}
          enterKeyHint="search"
          autoComplete="off"
          className="h-12 min-w-0 flex-1 bg-transparent text-[17px] text-[var(--ink)] outline-none"
        />
        <button
          type="submit"
          disabled={!canSubmit}
          className="inline-flex h-12 shrink-0 items-center justify-center gap-2 rounded-full bg-[var(--accent)] px-5 text-[15px] font-semibold text-[var(--on-accent)] transition-colors hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-40 sm:px-6"
        >
          {loading ? (
            <>
              <Spinner className="h-4 w-4" /> Thinking
            </>
          ) : (
            <>
              Find games <ArrowRight className="h-4 w-4" />
            </>
          )}
        </button>
      </form>
      <p id="search-hint" className="mt-3 hidden text-xs text-[var(--ink-faint)] sm:block">
        Press <kbd className="font-sans font-semibold">Enter</kbd> to search,{" "}
        <kbd className="font-sans font-semibold">Esc</kbd> to clear,{" "}
        <kbd className="font-sans font-semibold">/</kbd> to jump here.
      </p>

      <div className="mt-8 text-left">
        <p className="mb-2.5 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--label)]">
          Try an example
        </p>
        <ul className="grid gap-2 sm:grid-cols-3" aria-label="Example searches">
          {EXAMPLE_PROMPTS.map((ex) => (
            <li key={ex.prompt}>
              <button
                type="button"
                onClick={() => fill(ex.prompt)}
                className="flex min-h-11 w-full flex-col items-start rounded-2xl border border-[var(--border-strong)] bg-[var(--surface)] px-4 py-2.5 text-left transition-colors hover:bg-[var(--raised-2)]"
              >
                <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[var(--ink-faint)]">
                  {ex.label}
                </span>
                <span className="text-sm text-[var(--ink)]">{ex.prompt}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
});

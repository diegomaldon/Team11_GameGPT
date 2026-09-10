"use client";

import { useState } from "react";
import { recommend, sendFeedback, syncLibrary } from "@/lib/api/client";
import type { Recommendation, RecommendResponse, Vote } from "@/lib/api/types";
import {
  ArrowRight,
  Controller,
  External,
  Sparkle,
  Spinner,
  Star,
  ThumbDown,
  ThumbUp,
} from "./icons";

const EXAMPLES = [
  "a chill game I can play while listening to a podcast",
  "co-op night with friends who don't play much",
  "story-rich, under 10 hours",
  "hard roguelike with tight controls",
];

function scorePct(score?: number | null): number | null {
  if (score == null) return null;
  // Real API returns 0..1; fixtures use 0..100. Normalize either way.
  return Math.round(score <= 1 ? score * 100 : score);
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [voted, setVoted] = useState<Record<number, Vote>>({});

  const [steamId, setSteamId] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  async function run(q: string) {
    const trimmed = q.trim();
    if (!trimmed) return;
    setQuery(trimmed);
    setLoading(true);
    setError(null);
    setResult(null);
    setVoted({});
    try {
      setResult(await recommend(trimmed));
    } catch {
      setError("Couldn't reach the recommender. Is the API running?");
    } finally {
      setLoading(false);
    }
  }

  async function vote(rec: Recommendation, v: Vote) {
    if (!result) return;
    setVoted((prev) => ({ ...prev, [rec.rank]: v }));
    try {
      await sendFeedback({
        query_id: result.query_id,
        game_id: rec.game_id ?? null,
        title: rec.title,
        rank: rec.rank,
        vote: v,
      });
    } catch {
      /* optimistic; keep the UI state */
    }
  }

  async function onSync(e: React.FormEvent) {
    e.preventDefault();
    const id = steamId.trim();
    if (!id) return;
    setSyncing(true);
    setSyncMsg(null);
    setSyncError(null);
    try {
      const res = await syncLibrary(id);
      setSyncMsg(
        `Synced ${res.synced} game${res.synced === 1 ? "" : "s"} · source: ${res.source}`,
      );
    } catch {
      setSyncError("Sync failed. Check the steamID64 and that the profile is public.");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="min-h-dvh">
      <div className="mx-auto w-full max-w-3xl px-5 py-10 sm:px-6 sm:py-14">
        {/* ── Brand ── */}
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--ink)] text-white">
              <Controller className="h-5 w-5" />
            </span>
            <span className="font-display text-lg font-bold tracking-tight">
              GameGPT
            </span>
          </div>
          <span className="rounded-full border border-[var(--border)] bg-white px-2.5 py-1 text-xs font-medium text-[var(--ink-soft)]">
            beta
          </span>
        </header>

        {/* ── Hero + query ── */}
        <section className="mt-10 sm:mt-14">
          <h1 className="font-display text-3xl font-bold leading-[1.1] tracking-tight sm:text-[2.6rem]">
            Describe a vibe.
            <br />
            <span className="text-[var(--ink-soft)]">Get the game.</span>
          </h1>
          <p className="mt-3 max-w-md text-[15px] leading-relaxed text-[var(--ink-soft)]">
            Tell GameGPT what you&apos;re in the mood for. It searches a game
            knowledge base, skips what you already own, and ranks a short list.
          </p>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(query);
            }}
            className="mt-6"
          >
            <div className="flex flex-col gap-2 rounded-2xl border border-[var(--border)] bg-white p-2 shadow-card focus-within:border-accent-500 sm:flex-row sm:items-center sm:pl-4">
              <div className="flex flex-1 items-center gap-2.5">
                <Sparkle className="hidden h-5 w-5 shrink-0 text-[var(--ink-faint)] sm:block" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="a cozy game for a rainy afternoon…"
                  aria-label="Describe the game you want"
                  enterKeyHint="search"
                  className="w-full bg-transparent px-2 py-2.5 text-[15px] outline-none placeholder:text-[var(--ink-faint)] sm:px-0"
                />
              </div>
              <button
                type="submit"
                disabled={loading || !query.trim()}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-colors hover:bg-black disabled:cursor-not-allowed disabled:opacity-40"
              >
                {loading ? (
                  <>
                    <Spinner className="h-4 w-4" />
                    Thinking
                  </>
                ) : (
                  <>
                    Recommend
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </button>
            </div>
          </form>

          {/* Example prompts */}
          <div className="mt-3 flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => void run(ex)}
                disabled={loading}
                className="rounded-full border border-[var(--border)] bg-white px-3 py-1.5 text-[13px] text-[var(--ink-soft)] transition-colors hover:border-accent-200 hover:bg-accent-50 hover:text-accent-700 disabled:opacity-50"
              >
                {ex}
              </button>
            ))}
          </div>
        </section>

        {/* ── Results ── */}
        <section className="mt-10" aria-live="polite">
          {error && (
            <div
              role="alert"
              className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"
            >
              {error}
            </div>
          )}

          {loading && (
            <ul className="flex flex-col gap-3">
              {[0, 1, 2].map((i) => (
                <li
                  key={i}
                  className="shimmer flex gap-4 rounded-2xl border border-[var(--border)] bg-white p-5"
                >
                  <div className="h-11 w-11 shrink-0 rounded-xl bg-neutral-100" />
                  <div className="flex-1 space-y-2.5 py-1">
                    <div className="h-4 w-1/3 rounded bg-neutral-100" />
                    <div className="h-3 w-full rounded bg-neutral-100" />
                    <div className="h-3 w-4/5 rounded bg-neutral-100" />
                  </div>
                </li>
              ))}
            </ul>
          )}

          {result && !loading && (
            <>
              <div className="mb-4 flex items-baseline justify-between">
                <h2 className="text-sm font-semibold text-[var(--ink-soft)]">
                  {result.recommendations.length} picks for your vibe
                </h2>
                <span className="max-w-[55%] truncate text-xs text-[var(--ink-faint)]">
                  &ldquo;{result.query}&rdquo;
                </span>
              </div>

              <ul className="flex flex-col gap-3">
                {result.recommendations.map((rec, i) => {
                  const pct = scorePct(rec.review_score);
                  const top = rec.rank === 1;
                  return (
                    <li
                      key={`${rec.rank}-${rec.title}`}
                      className="group animate-fade-up rounded-2xl border border-[var(--border)] bg-white p-5 shadow-card transition-shadow hover:shadow-lift"
                      style={{ animationDelay: `${i * 60}ms` }}
                    >
                      <div className="flex gap-4">
                        {/* Rank */}
                        <div
                          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl font-display text-lg font-bold ${
                            top
                              ? "bg-accent-600 text-white"
                              : "bg-neutral-100 text-[var(--ink-soft)]"
                          }`}
                          aria-hidden
                        >
                          {rec.rank}
                        </div>

                        {/* Body */}
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                            <h3 className="font-display text-lg font-semibold leading-tight tracking-tight">
                              {rec.title}
                            </h3>
                            {pct != null && (
                              <span className="inline-flex items-center gap-1 rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-semibold text-[var(--ink-soft)]">
                                <Star className="h-3 w-3 text-amber-500" />
                                {pct}%
                              </span>
                            )}
                          </div>

                          <p className="mt-1.5 text-sm leading-relaxed text-[var(--ink-soft)]">
                            {rec.reason}
                          </p>

                          <div className="mt-3 flex items-center justify-between gap-3">
                            {rec.steam_appid ? (
                              <a
                                href={`https://store.steampowered.com/app/${rec.steam_appid}`}
                                target="_blank"
                                rel="noreferrer noopener"
                                className="inline-flex items-center gap-1.5 text-xs font-semibold text-accent-700 hover:text-accent-600"
                              >
                                View on Steam
                                <External className="h-3.5 w-3.5" />
                              </a>
                            ) : (
                              <span />
                            )}

                            {/* Feedback */}
                            <div className="flex items-center gap-1.5">
                              <span className="mr-1 hidden text-xs text-[var(--ink-faint)] sm:inline">
                                Good pick?
                              </span>
                              <VoteButton
                                label={`Thumbs up ${rec.title}`}
                                active={voted[rec.rank] === "up"}
                                tone="up"
                                onClick={() => void vote(rec, "up")}
                              >
                                <ThumbUp className="h-[18px] w-[18px]" />
                              </VoteButton>
                              <VoteButton
                                label={`Thumbs down ${rec.title}`}
                                active={voted[rec.rank] === "down"}
                                tone="down"
                                onClick={() => void vote(rec, "down")}
                              >
                                <ThumbDown className="h-[18px] w-[18px]" />
                              </VoteButton>
                            </div>
                          </div>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          {!result && !loading && !error && (
            <div className="rounded-2xl border border-dashed border-[var(--border)] bg-white/60 px-6 py-12 text-center">
              <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-neutral-100 text-[var(--ink-faint)]">
                <Sparkle className="h-5 w-5" />
              </span>
              <p className="mt-3 text-sm text-[var(--ink-soft)]">
                Your recommendations will appear here.
              </p>
              <p className="mt-1 text-xs text-[var(--ink-faint)]">
                Try a prompt above to get started.
              </p>
            </div>
          )}
        </section>

        {/* ── Steam sync ── */}
        <section className="mt-8 rounded-2xl border border-[var(--border)] bg-white p-5 shadow-card">
          <div className="flex items-center gap-2">
            <Controller className="h-4 w-4 text-[var(--ink-soft)]" />
            <h2 className="text-sm font-semibold">Link your Steam library</h2>
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-[var(--ink-soft)]">
            Paste a public steamID64. Owned games get filtered out of future
            recommendations.
          </p>
          <form onSubmit={onSync} className="mt-3 flex flex-col gap-2 sm:flex-row">
            <input
              value={steamId}
              onChange={(e) => setSteamId(e.target.value)}
              placeholder="76561197960287930"
              inputMode="numeric"
              aria-label="Public steamID64"
              className="h-11 w-full flex-1 rounded-xl border border-[var(--border)] bg-white px-3.5 text-sm outline-none transition-colors focus:border-accent-500"
            />
            <button
              type="submit"
              disabled={syncing || !steamId.trim()}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-[var(--border)] bg-white px-5 text-sm font-semibold transition-colors hover:border-neutral-300 hover:bg-neutral-50 disabled:opacity-40"
            >
              {syncing ? <Spinner className="h-4 w-4" /> : null}
              {syncing ? "Syncing" : "Sync library"}
            </button>
          </form>
          {syncMsg && (
            <p className="mt-2.5 inline-flex items-center gap-1.5 text-[13px] font-medium text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              {syncMsg}
            </p>
          )}
          {syncError && (
            <p role="alert" className="mt-2.5 text-[13px] text-rose-600">
              {syncError}
            </p>
          )}
        </section>

        <footer className="mt-10 text-center text-xs text-[var(--ink-faint)]">
          GameGPT · CIS454 walking skeleton
        </footer>
      </div>
    </div>
  );
}

function VoteButton({
  label,
  active,
  tone,
  onClick,
  children,
}: {
  label: string;
  active: boolean;
  tone: "up" | "down";
  onClick: () => void;
  children: React.ReactNode;
}) {
  const activeCls =
    tone === "up"
      ? "border-accent-600 bg-accent-50 text-accent-700"
      : "border-rose-300 bg-rose-50 text-rose-600";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      className={`flex h-11 w-11 items-center justify-center rounded-xl border transition-colors ${
        active
          ? activeCls
          : "border-[var(--border)] text-[var(--ink-faint)] hover:border-neutral-300 hover:bg-neutral-50 hover:text-[var(--ink-soft)]"
      }`}
    >
      {children}
    </button>
  );
}

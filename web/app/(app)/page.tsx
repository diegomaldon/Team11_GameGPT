"use client";

// Discover (TM11-142 layout; recommend + feedback from REQ011/REQ015). A rotating
// spotlight and a strip of popular games up top, then "Describe a vibe" with grouped
// suggested prompts, then the ranked picks. Any featured game can start a search for
// games like it; the page then scrolls to the results.

import { useRef, useState } from "react";
import { recommend, sendFeedback } from "@/lib/api/client";
import type { Recommendation, RecommendResponse, Vote } from "@/lib/api/types";
import { PROMPT_GROUPS, promptLike } from "@/lib/discover/featured";
import {
  ArrowRight,
  External,
  Search,
  Spinner,
  Star,
  ThumbDown,
  ThumbUp,
} from "@/components/icons";
import { cx } from "@/components/ui";
import { GameArt } from "@/components/discover/GameArt";
import { PopularStrip } from "@/components/discover/PopularStrip";
import { Spotlight } from "@/components/discover/Spotlight";

function scorePct(score?: number | null): number | null {
  if (score == null) return null;
  return Math.round(score <= 1 ? score * 100 : score);
}

export default function DiscoverPage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [voted, setVoted] = useState<Record<number, Vote>>({});
  const resultsRef = useRef<HTMLElement>(null);

  async function run(q: string) {
    const trimmed = q.trim();
    if (!trimmed) return;
    setQuery(trimmed);
    setLoading(true);
    setError(null);
    setResult(null);
    setVoted({});
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultsRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    try {
      setResult(await recommend(trimmed));
    } catch {
      setError("Couldn't reach the recommender. Is the API running?");
    } finally {
      setLoading(false);
    }
  }

  const findLike = (title: string) => void run(promptLike(title));

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
      /* optimistic */
    }
  }

  return (
    <>
      <h1 className="sr-only">Discover</h1>

      <Spotlight onFindLike={findLike} />
      <PopularStrip onFindLike={findLike} />

      <section aria-labelledby="vibe-heading" className="mx-auto mt-20 max-w-[880px] text-center sm:mt-24">
        <h2 id="vibe-heading" className="font-display text-[40px] leading-[1.05] sm:text-[56px]">
          Describe a vibe
        </h2>
        <p className="mx-auto mt-3.5 max-w-[560px] text-[17px] leading-relaxed text-[var(--ink-faint)]">
          Tell us how you want it to feel. We&apos;ll match it against the catalogue and leave
          out what you already own.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(query);
          }}
          className="mt-8 flex items-center gap-2 rounded-full border border-[var(--border-input)] bg-[var(--surface)] p-2 pl-5 text-left focus-within:border-[var(--accent)] sm:pl-6"
        >
          <Search className="hidden h-5 w-5 shrink-0 text-[var(--ink-faint)] sm:block" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="A cozy farming game I can play on Xbox…"
            aria-label="Describe the game you want"
            enterKeyHint="search"
            className="h-12 min-w-0 flex-1 bg-transparent text-[17px] text-[var(--ink)] outline-none"
          />
          <button
            type="submit"
            disabled={loading || !query.trim()}
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

        <div className="mt-10 grid gap-x-8 gap-y-6 text-left sm:grid-cols-2">
          {PROMPT_GROUPS.map((group) => (
            <div key={group.label}>
              <p className="mb-2.5 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--label)]">
                {group.label}
              </p>
              <div className="flex flex-wrap gap-2">
                {group.prompts.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => void run(ex)}
                    disabled={loading}
                    className="min-h-11 rounded-full border border-[var(--border-strong)] bg-[var(--surface)] px-4 text-left text-sm text-[var(--ink)] transition-colors hover:bg-[var(--raised-2)] disabled:opacity-50"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section
        ref={resultsRef}
        aria-live="polite"
        aria-label="Recommendations"
        className="mx-auto mt-14 max-w-[880px] scroll-mt-6"
      >
        {error && (
          <div
            role="alert"
            className="rounded-2xl border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-700"
          >
            {error}
          </div>
        )}

        {loading && (
          <ul className="flex flex-col gap-4">
            {[0, 1, 2].map((i) => (
              <li
                key={i}
                className="shimmer flex gap-5 rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5"
              >
                <div className="h-[126px] w-[84px] shrink-0 rounded-xl bg-[var(--raised-2)]" />
                <div className="flex-1 space-y-3 py-1">
                  <div className="h-5 w-1/3 rounded bg-[var(--raised-2)]" />
                  <div className="h-3 w-full rounded bg-[var(--raised-2)]" />
                  <div className="h-3 w-4/5 rounded bg-[var(--raised-2)]" />
                </div>
              </li>
            ))}
          </ul>
        )}

        {result && !loading && (
          <>
            <div className="mb-5 flex items-baseline justify-between gap-4">
              <h2 className="font-display text-[28px]">
                {result.recommendations.length} picks for your vibe
              </h2>
              <span className="max-w-[50%] truncate text-sm text-[var(--ink-faint)]">
                &ldquo;{result.query}&rdquo;
              </span>
            </div>

            <ul className="flex flex-col gap-4">
              {result.recommendations.map((rec, i) => {
                const pct = scorePct(rec.review_score);
                return (
                  <li
                    key={`${rec.rank}-${rec.title}`}
                    className="animate-fade-up rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5"
                    style={{ animationDelay: `${i * 60}ms` }}
                  >
                    <div className="flex gap-5">
                      <div className="relative h-[126px] w-[84px] shrink-0 overflow-hidden rounded-xl border border-[var(--border)]">
                        <GameArt appId={rec.steam_appid} title={rec.title} sizes="84px" decorative />
                        <span
                          aria-hidden
                          className={cx(
                            "absolute left-1.5 top-1.5 flex h-7 w-7 items-center justify-center rounded-full text-[13px] font-semibold",
                            rec.rank === 1
                              ? "bg-[var(--accent)] text-[var(--on-accent)]"
                              : "bg-[rgb(5_10_24/0.85)] text-[var(--heading)]",
                          )}
                        >
                          {rec.rank}
                        </span>
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                          <h3 className="font-display text-2xl leading-tight">
                            <span className="sr-only">{rec.rank}. </span>
                            {rec.title}
                          </h3>
                          {pct != null && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-[var(--raised-2)] px-2.5 py-0.5 text-xs font-semibold text-[var(--ink-soft)]">
                              <Star className="h-3 w-3 text-amber-500" />
                              {pct}%
                            </span>
                          )}
                        </div>
                        <p className="mt-2 text-[15px] leading-relaxed text-[var(--ink-soft)]">
                          {rec.reason}
                        </p>
                        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                          {rec.steam_appid ? (
                            <a
                              href={`https://store.steampowered.com/app/${rec.steam_appid}`}
                              target="_blank"
                              rel="noreferrer noopener"
                              className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-[var(--heading)] underline-offset-4 hover:underline"
                            >
                              View on Steam <External className="h-3.5 w-3.5" />
                            </a>
                          ) : (
                            <span />
                          )}
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
      </section>
    </>
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
      ? "border-[var(--accent)] bg-[var(--accent)] text-[var(--on-accent)]"
      : "border-rose-300 bg-rose-50 text-rose-600";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      className={cx(
        "flex h-11 w-11 items-center justify-center rounded-full border transition-colors",
        active
          ? activeCls
          : "border-[var(--border-strong)] text-[var(--ink-faint)] hover:bg-[var(--raised-2)] hover:text-[var(--heading)]",
      )}
    >
      {children}
    </button>
  );
}

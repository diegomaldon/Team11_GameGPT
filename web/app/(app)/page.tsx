"use client";

// Discover (TM11-142 layout; recommend + feedback from REQ011/REQ015). A rotating
// spotlight and a strip of popular games up top, then "Describe a vibe" with the search
// field and three example prompts (TM11-74), then the ranked picks. Any featured game
// can start a search for games like it; the page then scrolls to the results.
//
// The query that was searched stays on screen above its results, loading state, error
// or notice (TM11-74), even after the player starts typing a new one. With
// NEXT_PUBLIC_USE_FIXTURES=1 the page runs against canned results, no API needed.

import { useEffect, useRef, useState } from "react";
import { recommend, sendFeedback } from "@/lib/api/client";
import type { Recommendation, RecommendResponse, Vote } from "@/lib/api/types";
import { NO_RESULTS_MESSAGE, promptLike } from "@/lib/discover/featured";
import { External, Star, ThumbDown, ThumbUp } from "@/components/icons";
import { cx } from "@/components/ui";
import { GameArt } from "@/components/discover/GameArt";
import { PopularStrip } from "@/components/discover/PopularStrip";
import { SearchBox, type SearchBoxHandle } from "@/components/discover/SearchBox";
import { Spotlight } from "@/components/discover/Spotlight";

function scorePct(score?: number | null): number | null {
  if (score == null) return null;
  return Math.round(score <= 1 ? score * 100 : score);
}

export default function DiscoverPage() {
  const [query, setQuery] = useState("");
  // The query the results on screen are for. Separate from `query`, which is
  // whatever is in the field right now.
  const [submitted, setSubmitted] = useState<string | null>(null);
  const searchRef = useRef<SearchBoxHandle>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [voted, setVoted] = useState<Record<number, Vote>>({});
  const resultsRef = useRef<HTMLElement>(null);
  // The full example is cut mid-word behind the button on phones, so they get a shorter one.
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 640px)");
    const update = () => setWide(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  async function run(q: string) {
    const trimmed = q.trim();
    if (!trimmed || loading) return;
    setQuery(trimmed);
    setSubmitted(trimmed);
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

        <SearchBox
          ref={searchRef}
          value={query}
          onChange={setQuery}
          onSubmit={(q) => void run(q)}
          loading={loading}
          placeholder={wide ? "A cozy farming game I can play on Xbox…" : "A cozy farming game…"}
        />
      </section>

      <section
        ref={resultsRef}
        aria-live="polite"
        aria-label="Recommendations"
        className="mx-auto mt-14 max-w-[880px] scroll-mt-6"
      >
        {submitted && (
          <div
            data-testid="searched-query"
            className="mb-5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1"
          >
            <p className="min-w-0 break-words text-[15px] text-[var(--ink-soft)]">
              {loading ? "Searching for " : "You searched for "}
              <q className="font-semibold text-[var(--ink)]">{submitted}</q>
            </p>
            {!loading && submitted !== query && (
              <button
                type="button"
                onClick={() => searchRef.current?.fill(submitted)}
                className="min-h-11 shrink-0 text-sm font-semibold text-[var(--heading)] underline-offset-4 hover:underline"
              >
                Edit this search
              </button>
            )}
          </div>
        )}

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

        {result && !loading && result.notice && (
          // TM11-66: e.g. every match is already in the library. Said, never a blank list.
          <div
            role="status"
            className="mb-5 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-5 py-4 text-sm text-[var(--ink-soft)]"
          >
            {result.notice.message}
          </div>
        )}

        {result && !loading && !result.notice && result.recommendations.length === 0 && (
          // An empty list the API didn't explain (e.g. a guard dropped every pick).
          // Never a blank page. TM11-77 owns the full no-results state.
          <div
            role="status"
            className="mb-5 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-5 py-4 text-sm text-[var(--ink-soft)]"
          >
            {NO_RESULTS_MESSAGE}
          </div>
        )}

        {result && !loading && result.recommendations.length > 0 && (
          <>
            <h2 className="mb-5 font-display text-[28px]">
              {result.recommendations.length} picks for your vibe
            </h2>

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

"use client";

// Discover (TM11-142 layout; recommend + feedback from REQ011/REQ015). A rotating
// spotlight and a strip of popular games up top, then "Describe a vibe" with the search
// field and three example prompts (TM11-74), then the ranked picks. Any featured game
// can start a search for games like it; the page then scrolls to the results.
//
// The query that was searched stays on screen above its results, loading state, error
// or notice (TM11-74), even after the player starts typing a new one. With
// NEXT_PUBLIC_USE_FIXTURES=1 the page runs against canned results, no API needed.
//
// While a search runs, placeholder cards hold the results' place and a message says how
// far it has likely got (TM11-76, lib/discover/searchProgress.ts).
//
// TM11-77 (CIS453 search rainy-day scenario): an empty result suggests rephrasing and
// offers the example queries; a failed or timed-out search says so, with an estimated
// retry time and a Try again that re-runs the same query.
//
// Each pick is a RecommendationCard (TM11-75) in the pipeline's rank order; its title
// opens GameDetailPanel, and closing the panel returns focus to that title.
//
// TM11-78: below the results, Recent searches lists the last few queries with the
// games they found, and each of those opens the same detail panel.

import { useEffect, useRef, useState } from "react";
import { recommend, sendFeedback } from "@/lib/api/client";
import type { Recommendation, RecommendResponse, Vote } from "@/lib/api/types";
import { describeFailure, type FailureState } from "@/lib/api/failureState";
import { NO_RESULTS_MESSAGE, promptLike } from "@/lib/discover/featured";
import { searchProgressMessage } from "@/lib/discover/searchProgress";
import { ResultsSkeleton } from "@/components/Skeletons";
import { ServiceError } from "@/components/ServiceError";
import { NoResults } from "@/components/discover/NoResults";
import { rankedCards } from "@/lib/discover/recommendations";
import { GameDetailPanel } from "@/components/discover/GameDetailPanel";
import { targetFromRecommendation, type DetailTarget } from "@/lib/discover/gameDetail";
import { prefetchGames } from "@/lib/discover/gameDetailCache";
import { PopularStrip } from "@/components/discover/PopularStrip";
import { RecentSearches } from "@/components/discover/RecentSearches";
import { RecommendationCard } from "@/components/discover/RecommendationCard";
import { SearchBox, type SearchBoxHandle } from "@/components/discover/SearchBox";
import { Spotlight } from "@/components/discover/Spotlight";

export default function DiscoverPage() {
  const [query, setQuery] = useState("");
  // The query the results on screen are for. Separate from `query`, which is
  // whatever is in the field right now.
  const [submitted, setSubmitted] = useState<string | null>(null);
  const searchRef = useRef<SearchBoxHandle>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<FailureState | null>(null);
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [voted, setVoted] = useState<Record<number, Vote>>({});
  const [progressMessage, setProgressMessage] = useState(() => searchProgressMessage(0));
  // TM11-75/78: the game whose detail panel is open, and the button that opened it,
  // so focus can go back there when the panel closes.
  const [detail, setDetail] = useState<DetailTarget | null>(null);
  // Bumped after each search so Recent searches reloads and shows it.
  const [historyKey, setHistoryKey] = useState(0);
  const openerRef = useRef<HTMLElement | null>(null);
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

  // Restarts with every search, so each one's progress message starts from the top.
  // Setting the same message again doesn't re-render.
  useEffect(() => {
    if (!loading) {
      return;
    }
    const startedAt = Date.now();
    setProgressMessage(searchProgressMessage(0));
    const timer = window.setInterval(
      () => setProgressMessage(searchProgressMessage(Date.now() - startedAt)),
      250,
    );
    return () => window.clearInterval(timer);
  }, [loading]);

  async function run(q: string) {
    const trimmed = q.trim();
    if (!trimmed || loading) return;
    setQuery(trimmed);
    setSubmitted(trimmed);
    setLoading(true);
    setFailure(null);
    setResult(null);
    setVoted({});
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultsRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    try {
      const res = await recommend(trimmed);
      setResult(res);
      setHistoryKey((k) => k + 1);
      // Load each pick's details now, so opening a card is usually instant (TM11-78).
      prefetchGames(rankedCards(res.recommendations).map((r) => r.game_id));
    } catch (err) {
      setFailure(describeFailure(err, "search"));
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

  function openDetail(target: DetailTarget, opener: HTMLElement) {
    openerRef.current = opener;
    setDetail(target);
  }

  function closeDetail() {
    setDetail(null);
    openerRef.current?.focus();
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

        {failure && submitted && (
          <ServiceError failure={failure} onRetry={() => void run(submitted)} />
        )}

        {loading && <ResultsSkeleton message={progressMessage} />}

        {result && !loading && result.notice && result.recommendations.length > 0 && (
          // E.g. TM11-72's unranked fallback. With no results, NoResults shows the notice.
          <div
            role="status"
            className="mb-5 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-5 py-4 text-sm text-[var(--ink-soft)]"
          >
            {result.notice.message}
          </div>
        )}

        {result && !loading && result.recommendations.length === 0 && (
          // Never a blank page. The API's notice (e.g. TM11-66 all_owned) says why when it
          // knows; otherwise, e.g. when a guard dropped every pick, the generic tip does.
          <NoResults
            message={result.notice?.message ?? NO_RESULTS_MESSAGE}
            onPick={(prompt) => searchRef.current?.fill(prompt)}
          />
        )}

        {result && !loading && result.recommendations.length > 0 && (
          <>
            <h2 className="mb-5 font-display text-[28px]">
              {rankedCards(result.recommendations).length} picks for your vibe
            </h2>

            <ul className="flex flex-col gap-4">
              {rankedCards(result.recommendations).map((rec, i) => (
                <RecommendationCard
                  key={`${rec.rank}-${rec.title}`}
                  rec={rec}
                  index={i}
                  vote={voted[rec.rank]}
                  onVote={(r, v) => void vote(r, v)}
                  onOpen={(r, opener) => openDetail(targetFromRecommendation(r), opener)}
                />
              ))}
            </ul>
          </>
        )}
      </section>

      <RecentSearches refreshKey={historyKey} onOpen={openDetail} />

      <GameDetailPanel target={detail} onClose={closeDetail} />
    </>
  );
}

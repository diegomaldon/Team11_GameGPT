"use client";

// One ranked pick on Discover (TM11-75, REQ015): rank, cover art, title, platforms,
// review score and the explanation, plus the Steam link and thumbs up/down.
//
// The title opens the game's detail panel. The box keeps TM11-142's size (84×126 art,
// p-5), which TM11-76's ResultsSkeleton is drawn to; change both together.
// A game with no art gets its initials (GameArt), and one with no score or no store
// data says so instead of leaving a gap.

import type { Recommendation, Vote } from "@/lib/api/types";
import { platformLabels, scorePct } from "@/lib/discover/recommendations";
import { External, Star, ThumbDown, ThumbUp } from "@/components/icons";
import { cx } from "@/components/ui";
import { GameArt } from "@/components/discover/GameArt";

export function RecommendationCard({
  rec,
  index,
  vote,
  onVote,
  onOpen,
}: {
  rec: Recommendation;
  /** Position in the list, for the staggered entrance. */
  index: number;
  vote?: Vote;
  onVote: (rec: Recommendation, vote: Vote) => void;
  /** Open the detail panel. Gets the clicked element so focus can return to it. */
  onOpen: (rec: Recommendation, opener: HTMLElement) => void;
}) {
  const pct = scorePct(rec.review_score);
  const platforms = platformLabels(rec.platforms);

  return (
    <li
      data-testid="recommendation-card"
      className="animate-fade-up rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5"
      style={{ animationDelay: `${index * 60}ms` }}
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
              <span className="sr-only">{`${rec.rank}. `}</span>
              <button
                type="button"
                onClick={(e) => onOpen(rec, e.currentTarget)}
                aria-haspopup="dialog"
                aria-label={`${rec.title}, open details`}
                className="text-left underline-offset-4 hover:underline focus-visible:underline"
              >
                {rec.title}
              </button>
            </h3>
            {pct != null ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-[var(--raised-2)] px-2.5 py-0.5 text-xs font-semibold text-[var(--ink-soft)]">
                <Star className="h-3 w-3 text-amber-500" />
                {pct}%<span className="sr-only"> positive reviews</span>
              </span>
            ) : (
              <span className="text-xs text-[var(--ink-faint)]">No score yet</span>
            )}
          </div>

          <ul aria-label="Platforms" className="mt-2 flex flex-wrap gap-1.5">
            {platforms.length > 0 ? (
              platforms.map((label) => (
                <li
                  key={label}
                  className="rounded-full border border-[var(--border-strong)] px-2.5 py-0.5 text-xs text-[var(--ink-soft)]"
                >
                  {label}
                </li>
              ))
            ) : (
              <li className="text-xs text-[var(--ink-faint)]">Platforms not listed</li>
            )}
          </ul>

          <p className="mt-2 text-[15px] leading-relaxed text-[var(--ink-soft)]">{rec.reason}</p>

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
                active={vote === "up"}
                tone="up"
                onClick={() => onVote(rec, "up")}
              >
                <ThumbUp className="h-[18px] w-[18px]" />
              </VoteButton>
              <VoteButton
                label={`Thumbs down ${rec.title}`}
                active={vote === "down"}
                tone="down"
                onClick={() => onVote(rec, "down")}
              >
                <ThumbDown className="h-[18px] w-[18px]" />
              </VoteButton>
            </div>
          </div>
        </div>
      </div>
    </li>
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

"use client";

// The game detail panel (TM11-78, REQ009). It opens from a recommendation card
// (TM11-75), a library game and a past search, each of which hands it a DetailTarget,
// and fetches the rest from GET /api/games/{game_id}.
//
// AC: it shows the description, genre tags, platforms, and user and critic scores.
// AC: a missing field reads "Unavailable", never a blank or a broken value. That
// includes a game with no catalogue id or one the API doesn't know (404): the same
// layout shows, every field unavailable, rather than an error.
//
// Fetches go through lib/discover/gameDetailCache.ts, so a game opened before (or
// prefetched with Discover's results) shows at once. While a fetch runs, TM11-76's
// DetailSkeleton holds the panel's shape; a failed
// read shows TM11-77's "detail" ServiceError with a retry. Store links come only from
// the API's purchase_links; the contract says never to build one client-side.

import { useEffect, useState } from "react";
import { loadGame, peekGame } from "@/lib/discover/gameDetailCache";
import { ApiError } from "@/lib/api/apiError";
import type { GameDetail } from "@/lib/api/types";
import { describeFailure, type FailureState } from "@/lib/api/failureState";
import {
  criticScoreText,
  genreTags,
  namesText,
  platformsText,
  releaseYearText,
  storeLinks,
  UNAVAILABLE,
  userScoreText,
  type DetailTarget,
} from "@/lib/discover/gameDetail";
import { External } from "@/components/icons";
import { Modal, cx } from "@/components/ui";
import { DetailSkeleton } from "@/components/Skeletons";
import { ServiceError } from "@/components/ServiceError";
import { GameArt } from "@/components/discover/GameArt";

type Load =
  | { status: "loading" }
  | { status: "ready"; detail: GameDetail }
  /** No catalogue id, or the API has no such game: show the layout, all unavailable. */
  | { status: "missing" }
  | { status: "failed"; failure: FailureState };

export function GameDetailPanel({
  target,
  onClose,
}: {
  target: DetailTarget | null;
  onClose: () => void;
}) {
  if (!target) return null;
  return (
    <Modal open onClose={onClose} title={target.title} size="lg">
      {/* Keyed so opening another game starts from a clean fetch. */}
      <DetailBody key={target.gameId ?? `title:${target.title}`} target={target} />
    </Modal>
  );
}

function DetailBody({ target }: { target: DetailTarget }) {
  // Details already in the cache (opened before, or prefetched with the results) show
  // straight away, with no skeleton.
  const [load, setLoad] = useState<Load>(() => {
    if (!target.gameId) return { status: "missing" };
    const cached = peekGame(target.gameId);
    return cached ? { status: "ready", detail: cached } : { status: "loading" };
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const gameId = target.gameId;
    if (!gameId) return;
    if (attempt === 0 && peekGame(gameId)) return;
    let cancelled = false;
    setLoad({ status: "loading" });
    loadGame(gameId).then(
      (detail) => !cancelled && setLoad({ status: "ready", detail }),
      (err: unknown) => {
        if (cancelled) return;
        const notFound = err instanceof ApiError && err.code === "game_not_found";
        setLoad(
          notFound
            ? { status: "missing" }
            : { status: "failed", failure: describeFailure(err, "detail") },
        );
      },
    );
    return () => {
      cancelled = true;
    };
  }, [target.gameId, attempt]);

  if (load.status === "loading") return <DetailSkeleton />;
  if (load.status === "failed") {
    return <ServiceError failure={load.failure} onRetry={() => setAttempt((n) => n + 1)} />;
  }
  return <DetailLayout target={target} detail={load.status === "ready" ? load.detail : null} />;
}

/** The panel's content. `detail` is null when nothing more is known than the target. */
function DetailLayout({ target, detail }: { target: DetailTarget; detail: GameDetail | null }) {
  const { genres, tags } = genreTags(detail ?? { genres: [], tags: [] });
  const links = storeLinks(detail?.purchase_links);
  const owned = detail?.owned_on ?? [];

  return (
    <div data-testid="game-detail" className="flex flex-col gap-6">
      {!detail && (
        <p role="status" className="text-sm text-[var(--ink-faint)]">
          This game isn&apos;t in our catalogue yet, so its details are unavailable.
        </p>
      )}

      <div className="flex flex-col gap-5 sm:flex-row">
        <div className="relative aspect-[2/3] w-32 shrink-0 overflow-hidden rounded-[18px] border border-[var(--border)] bg-[var(--raised-2)] sm:w-40">
          <GameArt
            appId={detail?.steam_appid ?? target.steamAppid}
            title={target.title}
            sizes="160px"
            decorative
          />
        </div>

        <dl className="grid min-w-0 flex-1 grid-cols-2 content-start gap-x-4 gap-y-3 text-sm">
          <Fact label="User score" value={userScoreText(detail?.review_score)} />
          <Fact label="Critic score" value={criticScoreText(detail?.critic_score)} />
          <Fact
            label="Platforms"
            value={platformsText(detail ? detail.available_platforms : target.platforms)}
            wide
          />
          <Fact label="Released" value={releaseYearText(detail?.release_date)} />
          <Fact label="Developer" value={namesText(detail?.developers)} />
          {owned.length > 0 && <Fact label="In your library" value={platformsText(owned)} wide />}
        </dl>
      </div>

      <section aria-labelledby="detail-genres">
        <SectionHeading id="detail-genres">Genres and tags</SectionHeading>
        {genres.length + tags.length > 0 ? (
          <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Genres and tags">
            {genres.map((g) => (
              <li
                key={`g-${g}`}
                className="rounded-full bg-[var(--raised-2)] px-3 py-1 text-[13px] font-medium text-[var(--ink)]"
              >
                {g}
              </li>
            ))}
            {tags.map((t) => (
              <li
                key={`t-${t}`}
                className="rounded-full border border-[var(--border)] px-3 py-1 text-[13px] text-[var(--ink-soft)]"
              >
                {t}
              </li>
            ))}
          </ul>
        ) : (
          <Value text={UNAVAILABLE} className="mt-1.5" />
        )}
      </section>

      {target.reason && (
        <section aria-labelledby="detail-reason">
          <SectionHeading id="detail-reason">Why it fits</SectionHeading>
          <p className="mt-1.5 break-words text-[15px] leading-relaxed text-[var(--ink-soft)]">
            {target.reason}
          </p>
        </section>
      )}

      <section aria-labelledby="detail-about">
        <SectionHeading id="detail-about">About</SectionHeading>
        {detail?.description ? (
          <p className="mt-1.5 break-words text-[15px] leading-relaxed text-[var(--ink-soft)]">
            {detail.description}
          </p>
        ) : (
          <Value text={UNAVAILABLE} className="mt-1.5" />
        )}
      </section>

      <section aria-labelledby="detail-stores">
        <SectionHeading id="detail-stores">Where to buy</SectionHeading>
        {links.length > 0 ? (
          <ul className="mt-1 flex flex-wrap gap-x-5">
            {links.map((link) => (
              <li key={link.label}>
                <a
                  href={link.href}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-[var(--heading)] underline-offset-4 hover:underline"
                >
                  View on {link.label} <External className="h-3.5 w-3.5" />
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <Value text={UNAVAILABLE} className="mt-1.5" />
        )}
      </section>
    </div>
  );
}

function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h3 id={id} className="text-xs font-semibold uppercase tracking-[0.1em] text-[var(--label)]">
      {children}
    </h3>
  );
}

function Fact({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={cx("min-w-0", wide && "col-span-2")}>
      <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-[var(--label)]">
        {label}
      </dt>
      <dd className="mt-0.5">
        <Value text={value} />
      </dd>
    </div>
  );
}

/** A value, faded when it is the "Unavailable" placeholder so it reads as missing. */
function Value({ text, className }: { text: string; className?: string }) {
  const missing = text === UNAVAILABLE;
  return (
    <span
      className={cx(
        "block break-words",
        missing ? "text-sm text-[var(--ink-faint)]" : "text-[var(--ink)]",
        className,
      )}
    >
      {text}
    </span>
  );
}

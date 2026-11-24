"use client";

// The detail panel a result card opens (TM11-75 AC3). It shows what the recommend
// response already carries: art, title, platforms, score and the explanation.
//
// TM11-78 owns the full panel (description, genre tags, user and critic scores, and
// opening it from the library and history). It should replace the body below and
// keep the props, so the cards don't change. Missing fields say so rather than
// leaving a gap, which TM11-78's third AC asks for too.

import type { Recommendation } from "@/lib/api/types";
import { platformLabels, scorePct } from "@/lib/discover/recommendations";
import { External, Star } from "@/components/icons";
import { Modal } from "@/components/ui";
import { GameArt } from "@/components/discover/GameArt";

export function GameDetailPanel({
  rec,
  onClose,
}: {
  rec: Recommendation | null;
  onClose: () => void;
}) {
  if (!rec) return null;
  const pct = scorePct(rec.review_score);
  const platforms = platformLabels(rec.platforms);

  return (
    <Modal open onClose={onClose} title={rec.title}>
      <div className="flex gap-4">
        <div className="relative h-[150px] w-[100px] shrink-0 overflow-hidden rounded-xl border border-[var(--border)]">
          <GameArt appId={rec.steam_appid} title={rec.title} sizes="100px" decorative />
        </div>
        <dl className="min-w-0 flex-1 space-y-3 text-sm">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-[var(--label)]">
              Rank
            </dt>
            <dd className="text-[var(--ink)]">#{rec.rank} for your search</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-[var(--label)]">
              Platforms
            </dt>
            <dd className="text-[var(--ink)]">
              {platforms.length > 0 ? platforms.join(", ") : "Not listed"}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-[var(--label)]">
              Reviews
            </dt>
            <dd className="text-[var(--ink)]">
              {pct != null ? (
                <span className="inline-flex items-center gap-1">
                  <Star className="h-3.5 w-3.5 text-amber-500" /> {pct}% positive
                </span>
              ) : (
                "No score yet"
              )}
            </dd>
          </div>
        </dl>
      </div>

      <h3 className="mt-5 text-xs font-semibold uppercase tracking-[0.1em] text-[var(--label)]">
        Why it fits
      </h3>
      <p className="mt-1.5 text-[15px] leading-relaxed text-[var(--ink-soft)]">{rec.reason}</p>

      {rec.steam_appid ? (
        <a
          href={`https://store.steampowered.com/app/${rec.steam_appid}`}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-[var(--heading)] underline-offset-4 hover:underline"
        >
          View on Steam <External className="h-3.5 w-3.5" />
        </a>
      ) : (
        <p className="mt-4 text-sm text-[var(--ink-faint)]">No store link available.</p>
      )}
    </Modal>
  );
}
